from pathlib import Path

from fastapi import FastAPI
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from insights_platform.observability import get_logger

__all__ = ["MOUNT_NAME", "mount_frontend"]

MOUNT_NAME = "frontend"

_log = get_logger("insights.frontend")


def mount_frontend(app: FastAPI, *, dist: Path | None = None) -> bool:
    if dist is None:
        manifest_dir = getattr(app.state, "insights_manifest_dir", None)
        if manifest_dir is None:
            return False
        dist = Path(manifest_dir) / "frontend" / "dist"
    if not dist.is_dir():
        return False
    # The lifespan runs once per TestClient context, so a module-level app under test would
    # otherwise gain one more mount per test.
    if any(isinstance(route, Mount) and route.name == MOUNT_NAME for route in app.routes):
        return True
    app.mount("/", StaticFiles(directory=dist, html=True), name=MOUNT_NAME)
    _log.info("frontend.mounted", path=dist.as_posix())
    return True
