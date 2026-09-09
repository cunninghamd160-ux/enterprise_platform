import hashlib
import logging
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from insights_platform import config, context, data
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
    url = f"sqlite:///{tmp_path.as_posix()}/nested/warehouse.db"
    monkeypatch.setenv("INSIGHTS_CONN_WAREHOUSE_URL", url)
    monkeypatch.setenv("INSIGHTS_CONN_HR_API_URL", "http://hr-api.fixture")
    monkeypatch.setenv("INSIGHTS_CONN_HR_API_TOKEN", "fixture-token")
    monkeypatch.setattr(data, "_clients", {})
    monkeypatch.setattr(config, "_current", None)
    tokens = [(var, var.set(None)) for var in (context.principal, context.request_id)]
    yield
    for var, token in reversed(tokens):
        var.reset(token)


def declare(tmp_path: Path, *connections: str) -> None:
    body = MANIFEST.format(connections=", ".join(f'"{c}"' for c in connections))
    path = tmp_path / "platform.toml"
    path.write_text(body, encoding="utf-8")
    config.load(path)


def count_rows(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("select count(*) from compensation")).scalar_one()


def test_warehouse_returns_rows_and_creates_parent_dir(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse")
    assert count_rows(data.get_engine("warehouse")) > 0
    assert (tmp_path / "nested" / "warehouse.db").exists()


def test_get_connection_returns_engine_for_sql(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse")
    assert isinstance(data.get_connection("warehouse"), Engine)


def test_seed_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    declare(tmp_path, "warehouse")
    first = count_rows(data.get_engine("warehouse"))
    monkeypatch.setattr(data, "_clients", {})
    assert count_rows(data.get_engine("warehouse")) == first


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


def test_query_emits_audit_without_statement_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    declare(tmp_path, "warehouse")
    context.principal.set("u1")
    context.request_id.set("r1")
    engine = data.get_engine("warehouse")
    statement = "select base_salary from compensation where team = 'people-analytics'"
    with caplog.at_level(logging.INFO, logger="insights.audit"), engine.connect() as conn:
        conn.execute(text(statement)).all()
    records = [r for r in caplog.records if r.getMessage() == "data.query"]
    assert len(records) == 1
    fields = fields_of(records[0])
    assert fields["connection"] == "warehouse"
    assert fields["principal"] == "u1"
    assert fields["request_id"] == "r1"
    assert fields["statement_sha256"] == hashlib.sha256(statement.encode()).hexdigest()
    assert statement not in str(fields)


def test_hr_api_fixture_serves_json(tmp_path: Path) -> None:
    declare(tmp_path, "hr-api")
    client = data.get_http_client("hr-api")
    employees = client.get("/employees")
    assert employees.status_code == 200
    assert {e["id"] for e in employees.json()} >= {"E001", "E003"}
    assert client.get("/employees/E001").json()["team"] == "people-analytics"
    assert client.get("/employees/nope").status_code == 404


def test_http_request_emits_audit_without_query_string(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    declare(tmp_path, "hr-api")
    client = data.get_http_client("hr-api")
    with caplog.at_level(logging.INFO, logger="insights.audit"):
        client.get("/employees", params={"ssn": "000-00-0000"})
    records = [r for r in caplog.records if r.getMessage() == "data.request"]
    assert len(records) == 1
    fields = fields_of(records[0])
    assert fields["connection"] == "hr-api"
    assert fields["method"] == "GET"
    assert fields["target"] == "hr-api.fixture/employees"
    assert "000-00-0000" not in str(fields)


def test_timeouts_are_mandatory(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse", "hr-api")
    assert data.get_http_client("hr-api").timeout == httpx.Timeout(10.0)
    assert data.get_engine("warehouse").pool._pre_ping is True


def test_clients_are_cached(tmp_path: Path) -> None:
    declare(tmp_path, "hr-api")
    assert data.get_connection("hr-api") is data.get_connection("hr-api")


def test_wrong_kind_helpers_raise(tmp_path: Path) -> None:
    declare(tmp_path, "warehouse", "hr-api")
    with pytest.raises(data.WrongConnectionKindError):
        data.get_engine("hr-api")
    with pytest.raises(data.WrongConnectionKindError):
        data.get_http_client("warehouse")
