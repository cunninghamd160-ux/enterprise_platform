import logging
from collections.abc import Mapping
from typing import Final

from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Tracer

from insights_platform import context
from insights_platform.observability._otel import configure, current

__all__ = [
    "REQUIRED_FIELDS",
    "Logger",
    "Scalar",
    "configure",
    "fields_of",
    "flush",
    "get_logger",
    "get_meter",
    "get_tracer",
    "shutdown",
]

type Scalar = str | int | float | bool | None

REQUIRED_FIELDS: Final = ("app", "team", "principal", "request_id", "trace_id", "span_id")

_SCALAR_TYPES: Final = (str, int, float, bool, type(None))
_RESERVED_KEYS: Final = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
}


def _required_fields() -> dict[str, Scalar]:
    span_context = trace.get_current_span().get_span_context()
    valid = span_context.is_valid
    return {
        "app": context.app.get(),
        "team": context.team.get(),
        "principal": context.principal.get(),
        "request_id": context.request_id.get(),
        "trace_id": format(span_context.trace_id, "032x") if valid else None,
        "span_id": format(span_context.span_id, "016x") if valid else None,
    }


class Logger:
    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    def _emit(
        self, level: int, event: str, fields: Mapping[str, Scalar], *, exc_info: bool = False
    ) -> None:
        for key, value in fields.items():
            if key in _RESERVED_KEYS or key in REQUIRED_FIELDS:
                raise ValueError(f"log field {key!r} is reserved")
            if not isinstance(value, _SCALAR_TYPES):
                raise TypeError(f"log field {key!r} must be a scalar, got {type(value).__name__}")
        self._log.log(level, event, exc_info=exc_info, extra={**fields, **_required_fields()})

    def info(self, event: str, **fields: Scalar) -> None:
        self._emit(logging.INFO, event, fields)

    def warning(self, event: str, **fields: Scalar) -> None:
        self._emit(logging.WARNING, event, fields)

    def error(self, event: str, **fields: Scalar) -> None:
        self._emit(logging.ERROR, event, fields)

    def exception(self, event: str, **fields: Scalar) -> None:
        self._emit(logging.ERROR, event, fields, exc_info=True)


def get_logger(name: str) -> Logger:
    return Logger(name)


def fields_of(record: logging.LogRecord) -> dict[str, Scalar]:
    return {k: v for k, v in vars(record).items() if k not in _RESERVED_KEYS}


def get_meter(name: str) -> Meter:
    return metrics.get_meter(name)


def get_tracer(name: str) -> Tracer:
    return trace.get_tracer(name)


def flush() -> None:
    providers = current()
    if providers is not None:
        providers.logs.force_flush()
        providers.metrics.force_flush()
        providers.traces.force_flush()


def shutdown() -> None:
    providers = current()
    if providers is not None:
        providers.shutdown()
