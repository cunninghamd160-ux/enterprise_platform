import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    ConsoleLogRecordExporter,
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from insights_platform import audit, context
from insights_platform.observability import (
    REQUIRED_FIELDS,
    _otel,
    configure,
    fields_of,
    get_logger,
    get_tracer,
)

TEST_LOGGER = "insights.test"


def attrs(record: logging.LogRecord) -> dict[str, Any]:
    return record.__dict__


@pytest.fixture(autouse=True)
def configured() -> None:
    configure(app="demo", team="people-analytics")


@pytest.fixture
def captured(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    with caplog.at_level(logging.INFO, logger="insights"):
        yield caplog


def test_record_carries_required_fields(captured: pytest.LogCaptureFixture) -> None:
    get_logger(TEST_LOGGER).info("hello", x=1)
    record = attrs(captured.records[0])
    assert all(field in record for field in REQUIRED_FIELDS)
    assert record["x"] == 1
    assert captured.records[0].getMessage() == "hello"


def test_context_populates_principal_and_request_id(captured: pytest.LogCaptureFixture) -> None:
    principal_token = context.principal.set("u1")
    request_token = context.request_id.set("r-1")
    try:
        get_logger(TEST_LOGGER).info("hello")
    finally:
        context.principal.reset(principal_token)
        context.request_id.reset(request_token)
    record = attrs(captured.records[0])
    assert record["principal"] == "u1"
    assert record["request_id"] == "r-1"


def test_trace_ids_match_current_span(captured: pytest.LogCaptureFixture) -> None:
    with get_tracer("t").start_as_current_span("s") as span:
        get_logger(TEST_LOGGER).info("in-span")
        span_context = span.get_span_context()
    record = attrs(captured.records[0])
    assert record["trace_id"] == format(span_context.trace_id, "032x")
    assert record["span_id"] == format(span_context.span_id, "016x")
    assert len(record["trace_id"]) == 32 and len(record["span_id"]) == 16


def test_no_span_yields_none_ids(captured: pytest.LogCaptureFixture) -> None:
    get_logger(TEST_LOGGER).info("outside")
    record = attrs(captured.records[0])
    assert record["trace_id"] is None and record["span_id"] is None


def test_non_scalar_field_rejected() -> None:
    with pytest.raises(TypeError, match="'data'"):
        get_logger(TEST_LOGGER).info("bad", data={"a": 1})  # type: ignore[arg-type]


def test_reserved_field_rejected() -> None:
    with pytest.raises(ValueError, match="'name'"):
        get_logger(TEST_LOGGER).info("bad", name="x")


def test_caller_cannot_supply_required_fields() -> None:
    with pytest.raises(ValueError, match="'app'"):
        get_logger(TEST_LOGGER).info("spoof", app="spoof")


def test_audit_marks_stream(captured: pytest.LogCaptureFixture) -> None:
    audit.emit("authz.denied", route="/comp")
    record = captured.records[0]
    assert record.name == "insights.audit"
    assert attrs(record)[audit.STREAM_FIELD] == audit.STREAM
    assert attrs(record)["route"] == "/comp"


def test_audit_stream_cannot_be_overridden(captured: pytest.LogCaptureFixture) -> None:
    audit.emit("x", **{audit.STREAM_FIELD: "app"})
    assert attrs(captured.records[0])[audit.STREAM_FIELD] == audit.STREAM


def test_configure_is_idempotent() -> None:
    root = logging.getLogger(_otel.ROOT_LOGGER)
    before = [h for h in root.handlers if isinstance(h, _otel.Handler)]
    configure(app="other", team="other")
    configure(app="demo", team="people-analytics")
    after = [h for h in root.handlers if isinstance(h, _otel.Handler)]
    assert len(before) == len(after) == 1
    assert root.level == logging.INFO


def test_console_exporters_when_endpoint_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_otel.OTLP_ENDPOINT_ENV, raising=False)
    providers = _otel.build(app="a", team="t", out=io.StringIO())
    try:
        assert isinstance(providers.log_exporter, ConsoleLogRecordExporter)
        assert isinstance(providers.metric_exporter, ConsoleMetricExporter)
        assert isinstance(providers.span_exporter, ConsoleSpanExporter)
    finally:
        providers.shutdown()


def test_otlp_exporters_when_endpoint_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_otel.OTLP_ENDPOINT_ENV, "http://localhost:4318")
    providers = _otel.build(app="a", team="t", out=io.StringIO())
    try:
        assert isinstance(providers.log_exporter, OTLPLogExporter)
        assert isinstance(providers.metric_exporter, OTLPMetricExporter)
        assert isinstance(providers.span_exporter, OTLPSpanExporter)
    finally:
        providers.shutdown()


def test_resource_carries_tenant_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_otel.OTLP_ENDPOINT_ENV, raising=False)
    providers = _otel.build(app="comp", team="people-analytics", out=io.StringIO())
    try:
        resource = providers.resource.attributes
        assert resource["service.name"] == "comp"
        assert resource["insights.app"] == "comp"
        assert resource["insights.team"] == "people-analytics"
    finally:
        providers.shutdown()


def test_console_log_output_is_one_json_object_per_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_otel.OTLP_ENDPOINT_ENV, raising=False)
    out = io.StringIO()
    providers = _otel.build(app="a", team="t", out=out)
    logger = logging.getLogger("insights.console-test")
    handler = _otel.Handler(logger_provider=providers.logs)
    logger.addHandler(handler)
    try:
        get_logger("insights.console-test").info("line-one", x=1)
        get_logger("insights.console-test").info("line-two", x=2)
    finally:
        logger.removeHandler(handler)
        providers.shutdown()
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["body"] == "line-one"
    assert parsed[0]["attributes"]["x"] == 1
    assert parsed[0]["resource"]["attributes"]["insights.app"] == "a"


def test_exported_attributes_drop_none_and_keep_stream() -> None:
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    logger = logging.getLogger("insights.audit")
    handler = _otel.Handler(logger_provider=provider)
    logger.addHandler(handler)
    try:
        audit.emit("data.query", connection="warehouse")
    finally:
        logger.removeHandler(handler)
        provider.shutdown()
    (exported,) = exporter.get_finished_logs()
    exported_attrs = json.loads(exported.to_json(indent=None))["attributes"]
    assert exported_attrs[audit.STREAM_FIELD] == audit.STREAM
    assert exported_attrs["connection"] == "warehouse"
    assert "principal" not in exported_attrs
    assert "app" not in exported_attrs


def test_fields_of_returns_caller_and_required_fields_only(
    captured: pytest.LogCaptureFixture,
) -> None:
    get_logger(TEST_LOGGER).info("hello", connection="warehouse", n=1)
    fields = fields_of(captured.records[-1])
    assert fields["connection"] == "warehouse"
    assert fields["n"] == 1
    assert set(REQUIRED_FIELDS) <= set(fields)
    assert not {"name", "msg", "levelname", "message"} & set(fields)
