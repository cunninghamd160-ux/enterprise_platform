import hashlib
import logging
import os
import sys
from dataclasses import dataclass
from typing import IO, Any
from urllib.parse import urlsplit, urlunsplit

from opentelemetry import _logs, metrics, trace
from opentelemetry.attributes import BoundedAttributes
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler, LogRecordProcessor
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    ConsoleLogRecordExporter,
    LogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.util.types import AttributeValue

OTLP_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
ROOT_LOGGER = "insights"

SQL_TEXT_KEYS = frozenset({"db.statement", "db.query.text"})
URL_KEYS = frozenset({"http.url", "url.full", "http.target"})
DROPPED_KEYS = frozenset({"url.query"})
_SCRUBBED_KEYS = SQL_TEXT_KEYS | URL_KEYS | DROPPED_KEYS


@dataclass(frozen=True)
class Providers:
    resource: Resource
    logs: LoggerProvider
    metrics: MeterProvider
    traces: TracerProvider
    log_exporter: LogRecordExporter
    metric_exporter: MetricExporter
    span_exporter: SpanExporter

    def shutdown(self) -> None:
        self.logs.shutdown()
        self.metrics.shutdown()
        self.traces.shutdown()


class Handler(LoggingHandler):
    # OTel attributes cannot be null; unset required fields stay on the stdlib record but are
    # dropped from the export instead of producing a per-record warning.
    @staticmethod
    def _get_attributes(record: logging.LogRecord) -> dict[str, Any]:
        base = LoggingHandler._get_attributes(record) or {}
        return {key: value for key, value in base.items() if value is not None}


class ScrubbingSpanProcessor(SpanProcessor):
    # Span.end() freezes the attributes before any processor runs, so the span handed to the
    # wrapped processor is rebuilt with scrubbed attributes rather than edited in place.
    def __init__(self, inner: SpanProcessor) -> None:
        self._inner = inner

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        self._inner.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        self._inner.on_end(_scrub(span))

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


def _scrub(span: ReadableSpan) -> ReadableSpan:
    attributes = span.attributes or {}
    if _SCRUBBED_KEYS.isdisjoint(attributes):
        return span
    rebuilt = BoundedAttributes(
        attributes={
            key: _scrub_value(key, value)
            for key, value in attributes.items()
            if key not in DROPPED_KEYS
        }
    )
    rebuilt.dropped = span.dropped_attributes
    return ReadableSpan(
        name=span.name,
        context=span.get_span_context(),
        parent=span.parent,
        resource=span.resource,
        attributes=rebuilt,
        events=span.events,
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


def _scrub_value(key: str, value: AttributeValue) -> AttributeValue:
    if not isinstance(value, str):
        return value
    if key in SQL_TEXT_KEYS:
        return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"
    if key in URL_KEYS:
        return _without_query(value)
    return value


def _without_query(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return url.partition("?")[0].partition("#")[0]
    return urlunsplit((parts.scheme, parts.netloc.rpartition("@")[2], parts.path, "", ""))


def build(*, app: str, team: str, out: IO[str] = sys.stdout) -> Providers:
    resource = Resource.create({SERVICE_NAME: app, "insights.app": app, "insights.team": team})
    log_exporter: LogRecordExporter
    metric_exporter: MetricExporter
    span_exporter: SpanExporter
    log_processor: LogRecordProcessor
    span_processor: SpanProcessor

    if os.environ.get(OTLP_ENDPOINT_ENV):
        log_exporter = OTLPLogExporter()
        metric_exporter = OTLPMetricExporter()
        span_exporter = OTLPSpanExporter()
        log_processor = BatchLogRecordProcessor(log_exporter)
        span_processor = BatchSpanProcessor(span_exporter)
    else:
        log_exporter = ConsoleLogRecordExporter(
            out=out, formatter=lambda r: r.to_json(indent=None) + "\n"
        )
        metric_exporter = ConsoleMetricExporter(
            out=out, formatter=lambda m: m.to_json(indent=None) + "\n"
        )
        span_exporter = ConsoleSpanExporter(
            out=out, formatter=lambda s: s.to_json(indent=None) + "\n"
        )
        log_processor = SimpleLogRecordProcessor(log_exporter)
        span_processor = SimpleSpanProcessor(span_exporter)

    logs = LoggerProvider(resource=resource)
    logs.add_log_record_processor(log_processor)
    meter_provider = MeterProvider(
        resource=resource, metric_readers=[PeriodicExportingMetricReader(metric_exporter)]
    )
    traces = TracerProvider(resource=resource)
    traces.add_span_processor(ScrubbingSpanProcessor(span_processor))

    return Providers(
        resource=resource,
        logs=logs,
        metrics=meter_provider,
        traces=traces,
        log_exporter=log_exporter,
        metric_exporter=metric_exporter,
        span_exporter=span_exporter,
    )


_providers: Providers | None = None


def current() -> Providers | None:
    return _providers


def configure(*, app: str, team: str) -> None:
    global _providers
    if _providers is not None:
        return
    _providers = build(app=app, team=team)
    _logs.set_logger_provider(_providers.logs)
    metrics.set_meter_provider(_providers.metrics)
    trace.set_tracer_provider(_providers.traces)

    root = logging.getLogger(ROOT_LOGGER)
    root.setLevel(logging.INFO)
    root.addHandler(Handler(logger_provider=_providers.logs))
