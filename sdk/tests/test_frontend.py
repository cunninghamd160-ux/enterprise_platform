import logging
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.routing import Mount

from insights_platform import web
from insights_platform.auth import UnprotectedRouteError, public
from insights_platform.frontend import MOUNT_NAME, mount_frontend
from insights_platform.observability import fields_of
from insights_platform.testing import client_for

type ManifestWriter = Callable[..., Path]

INDEX = "<!doctype html><title>demo</title><div id=root></div>"
SCRIPT = "console.log('demo');"


def build_dist(directory: Path) -> Path:
    dist = directory / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "app.js").write_text(SCRIPT, encoding="utf-8")
    return dist


def mounts(app: FastAPI) -> list[Mount]:
    return [r for r in app.routes if isinstance(r, Mount) and r.name == MOUNT_NAME]


def test_dist_next_to_manifest_is_served_behind_every_route(
    tmp_path: Path, write_manifest: ManifestWriter
) -> None:
    build_dist(tmp_path)
    app = web.create_app(manifest=write_manifest())

    @app.get("/api")
    @public
    def api() -> dict[str, str]:
        return {"app": "demo"}

    with client_for(app) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert index.headers["content-type"].startswith("text/html")
        assert index.text == INDEX
        script = client.get("/assets/app.js")
        assert script.status_code == 200
        assert script.text == SCRIPT
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").status_code == 200
        assert client.get("/api").json() == {"app": "demo"}
        assert client.get("/missing").status_code == 404
    assert len(mounts(app)) == 1


def test_unmarked_route_fails_boot_before_anything_mounts(
    tmp_path: Path, write_manifest: ManifestWriter
) -> None:
    build_dist(tmp_path)
    app = web.create_app(manifest=write_manifest())

    @app.get("/unmarked")
    def unmarked() -> dict[str, str]:
        return {"ok": "never"}

    with pytest.raises(UnprotectedRouteError, match="GET /unmarked"), client_for(app):
        pass
    assert mounts(app) == []


def test_without_dist_nothing_is_mounted(write_manifest: ManifestWriter) -> None:
    app = web.create_app(manifest=write_manifest())
    assert mount_frontend(app) is False
    with client_for(app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/healthz").status_code == 200
    assert mounts(app) == []


def test_explicit_dist_mounts_once_and_logs(
    tmp_path: Path, write_manifest: ManifestWriter, caplog: pytest.LogCaptureFixture
) -> None:
    dist = build_dist(tmp_path / "built")
    app = web.create_app(manifest=write_manifest())
    assert mount_frontend(app, dist=tmp_path / "nowhere") is False
    with caplog.at_level(logging.INFO, logger="insights.frontend"):
        assert mount_frontend(app, dist=dist) is True
        assert mount_frontend(app, dist=dist) is True
    assert len(mounts(app)) == 1
    [mounted] = [fields_of(r) for r in caplog.records if r.getMessage() == "frontend.mounted"]
    assert mounted["path"] == dist.as_posix()
    with client_for(app) as client:
        assert client.get("/").text == INDEX
    assert len(mounts(app)) == 1


def test_app_without_manifest_dir_is_left_alone() -> None:
    assert mount_frontend(FastAPI()) is False
