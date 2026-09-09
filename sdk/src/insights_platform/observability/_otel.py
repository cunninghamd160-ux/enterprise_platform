import logging
import os
import sys
from dataclasses import dataclass
from typing import IO, Any

from opentelemetry import _logs, metrics, trace
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
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)

OTLP_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
ROOT_LOGGER = "insights"


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
    traces.add_span_processor(span_processor)

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
