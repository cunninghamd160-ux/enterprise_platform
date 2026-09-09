import importlib.util
import logging
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from insights_platform import config, data, web
from insights_platform._internal import manifest
from insights_platform.auth import UnprotectedRouteError, public, require_team
from insights_platform.data import _fixtures
from insights_platform.observability import fields_of
from insights_platform.testing import client_for, headers_for

type ManifestWriter = Callable[..., Path]

PA = headers_for("dana", team="people-analytics", roles=["analyst"])
FIN = headers_for("sam", team="finance")


def make_app(write_manifest: ManifestWriter, **manifest_kwargs: object) -> FastAPI:
    app = web.create_app(manifest=write_manifest(name="demo-web", **manifest_kwargs))

    @app.get("/open")
    @public
    async def open_route() -> dict[str, str]:
        return {"ok": "open"}

    @app.get("/comp")
    @require_team("people-analytics")
    async def comp() -> dict[str, str]:
        return {"ok": "comp"}

    return app


def counter_points(reader: InMemoryMetricReader, name: str) -> list[tuple[dict[str, object], int]]:
    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None
    found: list[tuple[dict[str, object], int]] = []
    for resource_metrics in metrics_data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == name:
                    found.extend(
                        (dict(point.attributes or {}), int(point.value))
                        for point in metric.data.data_points
                    )
    return found


def test_health_and_readiness(write_manifest: ManifestWriter) -> None:
    with client_for(make_app(write_manifest)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json() == {"status": "ok"}


def test_readiness_pings_every_connection(
    write_manifest: ManifestWriter, caplog: pytest.LogCaptureFixture
) -> None:
    app = make_app(write_manifest, connections=("warehouse", "hr-api"))
    with caplog.at_level(logging.INFO, logger="insights.audit"), client_for(app) as client:
        assert client.get("/readyz").status_code == 200
    events = {r.getMessage() for r in caplog.records}
    assert {"data.query", "data.request"} <= events


def test_unreachable_connection_is_not_ready(
    write_manifest: ManifestWriter, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("hr-api", request=request)

    monkeypatch.setattr(_fixtures, "hr_api_handler", unreachable)
    app = make_app(write_manifest, connections=("warehouse", "hr-api"))
    with client_for(app) as client:
        assert client.get("/healthz").status_code == 200
        ready = client.get("/readyz")
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable", "error": "ConnectTimeout"}


def test_create_app_records_manifest_dir(write_manifest: ManifestWriter, tmp_path: Path) -> None:
    app_dir = tmp_path / "apps" / "demo-web"
    app = web.create_app(manifest=write_manifest(app_dir, name="demo-web"))
    assert app.state.insights_manifest_dir == app_dir.resolve()


def test_protected_route_enforced(write_manifest: ManifestWriter) -> None:
    with client_for(make_app(write_manifest)) as client:
        assert client.get("/open").status_code == 200
        assert client.get("/comp").status_code == 401
        assert client.get("/comp", headers=FIN).status_code == 403
        assert client.get("/comp", headers=PA).json() == {"ok": "comp"}


def test_request_counter_and_log(
    write_manifest: ManifestWriter,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(web, "get_meter", provider.get_meter)
    app = make_app(write_manifest)

    with caplog.at_level(logging.INFO, logger="insights.web"), client_for(app) as client:
        client.get("/comp", headers=PA)
        client.get("/comp/extra")

    points = {
        frozenset(attrs.items()): value
        for attrs, value in counter_points(reader, "insights.http.requests")
    }
    assert points[frozenset({("route", "/comp"), ("method", "GET"), ("status", 200)})] == 1
    assert points[frozenset({("route", "unmatched"), ("method", "GET"), ("status", 404)})] == 1

    completed = [fields_of(r) for r in caplog.records if r.getMessage() == "request.completed"]
    comp = next(f for f in completed if f["route"] == "/comp")
    assert comp["method"] == "GET"
    assert comp["status"] == 200
    assert comp["principal"] == "dana"
    assert isinstance(comp["duration_ms"], float)
    assert comp["request_id"]


def test_unmarked_route_fails_startup(write_manifest: ManifestWriter) -> None:
    app = web.create_app(manifest=write_manifest())

    @app.get("/unmarked")
    async def unmarked() -> dict[str, str]:
        return {"ok": "never"}

    with pytest.raises(UnprotectedRouteError, match="GET /unmarked"), client_for(app):
        pass


def test_missing_credential_is_not_ready(
    write_manifest: ManifestWriter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INSIGHTS_CONN_WAREHOUSE_URL")
    app = make_app(write_manifest)

    ready = TestClient(app).get("/readyz")
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable", "error": "MissingCredentialError"}

    with pytest.raises(data.MissingCredentialError), client_for(app):
        pass


def test_job_manifest_rejected(write_manifest: ManifestWriter) -> None:
    with pytest.raises(config.ConfigError, match="requires kind = 'web'"):
        web.create_app(manifest=write_manifest(kind="job"))


def test_manifest_discovered_from_caller_not_cwd(
    tmp_path: Path, write_manifest: ManifestWriter, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_dir = tmp_path / "apps" / "demo-web"
    write_manifest(app_dir, name="demo-web")
    write_manifest(tmp_path / "elsewhere", name="other")
    monkeypatch.chdir(tmp_path / "elsewhere")

    module_path = app_dir / "src" / "demo_web" / "main.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text(
        "from insights_platform.web import create_app\napp = create_app()\n", encoding="utf-8"
    )
    spec = importlib.util.spec_from_file_location("demo_web_main", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.app.title == "demo-web"
    assert module.app.state.insights_manifest_dir == app_dir.resolve()
    assert config.current().name == "demo-web"


def test_manifest_falls_back_to_cwd(
    tmp_path: Path, write_manifest: ManifestWriter, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = write_manifest(tmp_path / "cwd-app")
    monkeypatch.chdir(tmp_path / "cwd-app")
    assert manifest.resolve(None, "<string>") == expected
    assert manifest.resolve(None, None) == expected
    assert manifest.resolve(Path("explicit.toml"), None) == Path("explicit.toml")


def test_locate_walks_upward_and_fails_cleanly(
    tmp_path: Path, write_manifest: ManifestWriter
) -> None:
    expected = write_manifest(tmp_path / "root")
    assert config.locate(tmp_path / "root" / "src" / "pkg") == expected
    with pytest.raises(config.ConfigError, match=r"no platform\.toml"):
        config.locate(tmp_path / "empty")
