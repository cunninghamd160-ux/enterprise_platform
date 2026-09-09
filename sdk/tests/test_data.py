import asyncio
import hashlib
import logging
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import sqlalchemy.ext.asyncio
from sqlalchemy import text
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncEngine

from insights_platform import config, context, data
from insights_platform.data import _fixtures
from insights_platform.observability import fields_of

MANIFEST = """
[app]
name = "demo"
team = "people-analytics"
kind = "web"
scaffold_version = "0.1.0"
connections = [{connections}]
"""


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    url = f"sqlite+aiosqlite:///{tmp_path.as_posix()}/nested/warehouse.db"
    monkeypatch.setenv("INSIGHTS_CONN_WAREHOUSE_URL", url)
    monkeypatch.setenv("INSIGHTS_CONN_HR_API_URL", "http://hr-api.fixture")
    monkeypatch.setenv("INSIGHTS_CONN_HR_API_TOKEN", "fixture-token")
    monkeypatch.setattr(config, "_current", None)
    data.reset_clients()
    tokens = [(var, var.set(None)) for var in (context.principal, context.request_id)]
    yield
    for var, token in reversed(tokens):
        var.reset(token)
    data.reset_clients()


def declare(tmp_path: Path, *connections: str) -> None:
    body = MANIFEST.format(connections=", ".join(f'"{c}"' for c in connections))
    path = tmp_path / "platform.toml"
    path.write_text(body, encoding="utf-8")
    config.load(path)


async def count_rows(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(text("select count(*) from compensation"))
        return int(result.scalar_one())


def audit_records(caplog: pytest.LogCaptureFixture, event: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == event]


def test_warehouse_returns_rows_and_creates_parent_dir(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse")
    assert asyncio.run(count_rows(data.get_engine("warehouse"))) > 0
    assert (tmp_path / "nested" / "warehouse.db").exists()


def test_get_connection_returns_async_engine_for_sql(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse")
    engine = data.get_connection("warehouse")
    assert isinstance(engine, AsyncEngine)
    assert engine.url.drivername == "sqlite+aiosqlite"


def test_sync_driver_url_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    declare(tmp_path, "warehouse")
    monkeypatch.setenv("INSIGHTS_CONN_WAREHOUSE_URL", f"sqlite:///{tmp_path.as_posix()}/sync.db")
    with pytest.raises(InvalidRequestError, match="async driver"):
        data.get_engine("warehouse")


def test_seed_is_idempotent(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse")
    first = asyncio.run(count_rows(data.get_engine("warehouse")))
    data.reset_clients()
    assert asyncio.run(count_rows(data.get_engine("warehouse"))) == first


def test_engine_built_outside_a_loop_is_usable_on_any_loop(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse")
    engine = data.get_engine("warehouse")
    assert asyncio.run(count_rows(engine)) == asyncio.run(count_rows(engine))


def test_undeclared_connection_raises(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse")
    with pytest.raises(data.ConnectionNotDeclaredError, match="hr-api"):
        data.get_connection("hr-api")


def test_unknown_connection_raises_at_validate(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse", "lakehouse")
    with pytest.raises(data.UnknownConnectionError, match="lakehouse"):
        data.validate_connections()


def test_missing_credential_names_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    declare(tmp_path, "warehouse")
    monkeypatch.delenv("INSIGHTS_CONN_WAREHOUSE_URL")
    with pytest.raises(data.MissingCredentialError, match="INSIGHTS_CONN_WAREHOUSE_URL"):
        data.get_connection("warehouse")


def test_validate_fails_fast_on_missing_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    declare(tmp_path, "warehouse", "hr-api")
    monkeypatch.delenv("INSIGHTS_CONN_HR_API_TOKEN")
    with pytest.raises(data.MissingCredentialError, match="INSIGHTS_CONN_HR_API_TOKEN"):
        data.validate_connections()


def test_validate_constructs_every_declared_connection(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse", "hr-api")
    data.validate_connections()
    assert set(data._clients) == {"warehouse", "hr-api"}


def test_ping_reaches_every_declared_connection(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    declare(tmp_path, "warehouse", "hr-api")
    probe = httpx.Request("HEAD", "http://hr-api.fixture/")
    assert _fixtures.hr_api_handler(probe).status_code == 405
    with caplog.at_level(logging.INFO, logger="insights.audit"):
        asyncio.run(data.ping_connections())
    [query] = audit_records(caplog, "data.query")
    assert fields_of(query)["connection"] == "warehouse"
    [request] = audit_records(caplog, "data.request")
    assert fields_of(request)["method"] == "HEAD"
    assert fields_of(request)["target"] == "hr-api.fixture/"


def test_ping_fails_on_transport_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("hr-api", request=request)

    monkeypatch.setattr(_fixtures, "hr_api_handler", unreachable)
    declare(tmp_path, "hr-api")
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(data.ping_connections())


def test_ping_surfaces_construction_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    declare(tmp_path, "warehouse")
    monkeypatch.delenv("INSIGHTS_CONN_WAREHOUSE_URL")
    with pytest.raises(data.MissingCredentialError):
        asyncio.run(data.ping_connections())


def test_query_emits_audit_without_statement_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    declare(tmp_path, "warehouse")
    context.principal.set("u1")
    context.request_id.set("r1")
    engine = data.get_engine("warehouse")
    statement = "select base_salary from compensation where team = 'people-analytics'"

    async def query() -> None:
        async with engine.connect() as conn:
            (await conn.execute(text(statement))).all()

    with caplog.at_level(logging.INFO, logger="insights.audit"):
        asyncio.run(query())
    [record] = audit_records(caplog, "data.query")
    fields = fields_of(record)
    assert fields["connection"] == "warehouse"
    assert fields["principal"] == "u1"
    assert fields["request_id"] == "r1"
    assert fields["statement_sha256"] == hashlib.sha256(statement.encode()).hexdigest()
    assert statement not in str(fields)


def test_hr_api_fixture_serves_json(tmp_path: Path) -> None:
    declare(tmp_path, "hr-api")
    client = data.get_http_client("hr-api")

    async def scenario() -> None:
        employees = await client.get("/employees")
        assert employees.status_code == 200
        assert {e["id"] for e in employees.json()} >= {"E001", "E003"}
        assert (await client.get("/employees/E001")).json()["team"] == "people-analytics"
        assert (await client.get("/employees/nope")).status_code == 404

    asyncio.run(scenario())


def test_http_request_emits_audit_without_query_string(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    declare(tmp_path, "hr-api")
    client = data.get_http_client("hr-api")
    with caplog.at_level(logging.INFO, logger="insights.audit"):
        asyncio.run(client.get("/employees", params={"ssn": "000-00-0000"}))
    [record] = audit_records(caplog, "data.request")
    fields = fields_of(record)
    assert fields["connection"] == "hr-api"
    assert fields["method"] == "GET"
    assert fields["target"] == "hr-api.fixture/employees"
    assert "000-00-0000" not in str(fields)


def test_timeouts_are_mandatory(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse", "hr-api")
    assert data.get_http_client("hr-api").timeout == httpx.Timeout(10.0)
    assert data.get_engine("warehouse").pool._pre_ping is True


def test_construction_attaches_instrumentation(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse", "hr-api")
    data.get_engine("warehouse")
    assert hasattr(sqlalchemy.ext.asyncio.create_async_engine, "__wrapped__")
    client = data.get_http_client("hr-api")
    assert getattr(client, "_is_instrumented_by_opentelemetry", False) is True


def test_clients_are_cached(tmp_path: Path) -> None:
    declare(tmp_path, "hr-api")
    assert data.get_connection("hr-api") is data.get_connection("hr-api")


def test_reset_clients_disposes_engines_and_closes_clients(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse", "hr-api")
    engine = data.get_engine("warehouse")
    client = data.get_http_client("hr-api")
    asyncio.run(count_rows(engine))
    assert engine.pool.checkedin() == 1
    data.reset_clients()
    assert engine.pool.checkedin() == 0
    assert client.is_closed
    assert data._clients == {}


def test_wrong_kind_helpers_raise(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse", "hr-api")
    with pytest.raises(data.WrongConnectionKindError):
        data.get_engine("hr-api")
    with pytest.raises(data.WrongConnectionKindError):
        data.get_http_client("warehouse")
