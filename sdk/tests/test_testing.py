import logging
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import text

from insights_platform import config, data, web
from insights_platform.auth import Principal, public
from insights_platform.auth.sso import principal_from_headers
from insights_platform.observability import fields_of
from insights_platform.testing import client_for, headers_for

type ManifestWriter = Callable[..., Path]


def test_headers_for_round_trips_through_sso_stub() -> None:
    headers = headers_for("dana", team="people-analytics", roles=["analyst", "viewer"])
    assert principal_from_headers(headers) == Principal(
        user="dana", team="people-analytics", roles=frozenset({"analyst", "viewer"})
    )
    assert principal_from_headers(headers_for("sam", team="finance")) == Principal(
        user="sam", team="finance", roles=frozenset()
    )


def test_client_for_runs_startup_checks(
    write_manifest: ManifestWriter, caplog: pytest.LogCaptureFixture
) -> None:
    app = web.create_app(manifest=write_manifest())

    @app.get("/open")
    @public
    def open_route() -> dict[str, str]:
        return {"ok": "open"}

    with caplog.at_level(logging.INFO, logger="insights.web"), client_for(app) as client:
        assert client.get("/open").status_code == 200

    [started] = [fields_of(r) for r in caplog.records if r.getMessage() == "app.started"]
    assert started["routes"] == 3


def test_fixture_env_provides_connections_without_dotenv(
    tmp_path: Path, write_manifest: ManifestWriter
) -> None:
    config.load(write_manifest())
    engine = data.get_engine("warehouse")
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from compensation")).scalar_one() > 0
    assert Path(str(engine.url.database)).is_relative_to(tmp_path)
