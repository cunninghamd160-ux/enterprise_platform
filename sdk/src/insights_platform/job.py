import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

from opentelemetry.trace import Status, StatusCode

from insights_platform import config, context, data, observability
from insights_platform._internal import manifest as _manifest
from insights_platform.observability import get_logger, get_meter, get_tracer

_log = get_logger("insights.job")


def run_job(fn: Callable[[], Awaitable[object]], *, manifest: Path | None = None) -> int:
    cfg = config.load(_manifest.resolve(manifest, _manifest.caller_file()))
    if cfg.kind != "job":
        raise config.ConfigError(f"{cfg.name} is a {cfg.kind} app; run_job() requires kind = 'job'")
    observability.configure(app=cfg.name, team=cfg.team)
    runs = get_meter("insights.job").create_counter(
        "insights.job.runs", unit="1", description="Job runs by status"
    )

    principal_token = context.principal.set(f"job:{cfg.name}")
    request_token = context.request_id.set(uuid4().hex)
    started = time.perf_counter()
    try:
        with get_tracer("insights.job").start_as_current_span("job.run") as span:
            try:
                data.validate_connections()
                asyncio.run(_await(fn))
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
                _log.exception(
                    "job.completed",
                    status="failed",
                    duration_ms=_elapsed_ms(started),
                    error=type(exc).__name__,
                )
                runs.add(1, {"status": "failed"})
                return 1
            _log.info("job.completed", status="ok", duration_ms=_elapsed_ms(started))
            runs.add(1, {"status": "ok"})
            return 0
    finally:
        context.principal.reset(principal_token)
        context.request_id.reset(request_token)
        observability.flush()


async def _await(fn: Callable[[], Awaitable[object]]) -> object:
    return await fn()


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
