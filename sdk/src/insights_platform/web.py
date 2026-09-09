import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.metrics import Counter
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from insights_platform import auth, config, data, frontend, observability
from insights_platform._internal import manifest as _manifest
from insights_platform.observability import get_logger, get_meter

_log = get_logger("insights.web")


def create_app(*, manifest: Path | None = None) -> FastAPI:
    manifest_path = _manifest.resolve(manifest, _manifest.caller_file())
    cfg = config.load(manifest_path)
    if cfg.kind != "web":
        raise config.ConfigError(
            f"{cfg.name} is a {cfg.kind} app; create_app() requires kind = 'web'"
        )
    observability.configure(app=cfg.name, team=cfg.team)

    requests = get_meter("insights.web").create_counter(
        "insights.http.requests", unit="1", description="HTTP requests by route, method, status"
    )
    app = FastAPI(title=cfg.name, lifespan=_lifespan)
    app.state.insights_manifest_dir = manifest_path.resolve().parent
    # Added before auth so it sits inside the SSO middleware and sees the request's principal.
    app.add_middleware(_RequestMetrics, counter=requests)
    auth.install(app)
    _add_health_routes(app)
    FastAPIInstrumentor.instrument_app(app)
    return app


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    auth.check_routes(app)
    frontend.mount_frontend(app)
    data.validate_connections()
    _log.info("app.started", routes=len([r for r in app.routes if isinstance(r, APIRoute)]))
    yield
    observability.flush()


def _add_health_routes(app: FastAPI) -> None:
    @app.get("/healthz")
    @auth.public
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    @auth.public
    async def readyz() -> JSONResponse:
        try:
            await data.ping_connections()
        except Exception as exc:
            return JSONResponse(
                {"status": "unavailable", "error": type(exc).__name__}, status_code=503
            )
        return JSONResponse({"status": "ok"})


def _route_template(scope: Scope) -> str:
    endpoint = scope.get("endpoint")
    for route in scope["app"].routes:
        if isinstance(route, APIRoute) and route.endpoint is endpoint:
            return str(route.path)
    return "unmatched"


class _RequestMetrics:
    def __init__(self, app: ASGIApp, counter: Counter) -> None:
        self.app = app
        self.counter = counter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status = 500

        async def record_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, record_status)
        finally:
            route = _route_template(scope)
            method = str(scope["method"])
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            self.counter.add(1, {"route": route, "method": method, "status": status})
            _log.info(
                "request.completed",
                route=route,
                method=method,
                status=status,
                duration_ms=duration_ms,
            )
