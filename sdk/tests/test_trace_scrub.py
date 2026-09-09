import asyncio
import hashlib
import io
import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.util.types import AttributeValue
from sqlalchemy import text

from insights_platform import config, data, web
from insights_platform.auth import public
from insights_platform.observability import _otel, configure, fields_of
from insights_platform.testing import client_for

type ManifestWriter = Callable[..., Path]

STATEMENT = "select base_salary from compensation where employee_id = 'E001'"
STATEMENT_SHA256 = hashlib.sha256(STATEMENT.encode()).hexdigest()
SSN = "000-00-0000"


class Recording(SpanProcessor):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.ended: list[ReadableSpan] = []

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        self.calls.append("on_start")

    def on_end(self, span: ReadableSpan) -> None:
        self.calls.append("on_end")
        self.ended.append(span)

    def shutdown(self) -> None:
        self.calls.append("shutdown")

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        self.calls.append("force_flush")
        return True


def scrubbed_provider(
    processor: Callable[[InMemorySpanExporter], SpanProcessor] = SimpleSpanProcessor,
) -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(_otel.ScrubbingSpanProcessor(processor(exporter)))
    return provider, exporter


def emit(
    provider: TracerProvider, attributes: dict[str, AttributeValue], *, name: str = "s"
) -> None:
    provider.get_tracer("test").start_span(name, attributes=attributes).end()


def attrs_of(span: ReadableSpan) -> dict[str, AttributeValue]:
    return dict(span.attributes or {})


def only(exporter: InMemorySpanExporter) -> ReadableSpan:
    (span,) = exporter.get_finished_spans()
    return span


def run_query(statement: str) -> None:
    async def query() -> None:
        async with data.get_engine("warehouse").connect() as conn:
            (await conn.execute(text(statement))).all()

    asyncio.run(query())


def send_request(path: str, params: dict[str, str]) -> None:
    asyncio.run(data.get_http_client("hr-api").get(path, params=params))


@pytest.fixture
def exported() -> Iterator[InMemorySpanExporter]:
    configure(app="demo", team="people-analytics")
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    exporter = InMemorySpanExporter()
    processor = _otel.ScrubbingSpanProcessor(SimpleSpanProcessor(exporter))
    provider.add_span_processor(processor)
    yield exporter
    processor.shutdown()


def test_sql_text_is_replaced_by_its_sha256() -> None:
    provider, exporter = scrubbed_provider()
    emit(
        provider,
        {"db.statement": STATEMENT, "db.query.text": STATEMENT, "db.system": "sqlite"},
        name="SELECT warehouse",
    )
    span = only(exporter)
    attrs = attrs_of(span)
    assert attrs["db.statement"] == f"sha256:{STATEMENT_SHA256}"
    assert attrs["db.query.text"] == f"sha256:{STATEMENT_SHA256}"
    assert attrs["db.system"] == "sqlite"
    assert span.name == "SELECT warehouse"
    assert "E001" not in span.to_json()
    provider.shutdown()


def test_urls_keep_scheme_host_path_and_lose_query_fragment_and_userinfo() -> None:
    url = f"https://svc-account@hr-api.fixture:8443/employees?ssn={SSN}#top"
    provider, exporter = scrubbed_provider()
    emit(
        provider,
        {
            "http.url": url,
            "url.full": url,
            "http.target": f"/employees?ssn={SSN}",
            "url.path": "/employees",
            "url.query": f"ssn={SSN}",
            "http.status_code": 200,
        },
    )
    span = only(exporter)
    attrs = attrs_of(span)
    assert attrs["http.url"] == attrs["url.full"] == "https://hr-api.fixture:8443/employees"
    assert attrs["http.target"] == "/employees"
    assert attrs["url.path"] == "/employees"
    assert "url.query" not in attrs
    assert attrs["http.status_code"] == 200
    assert SSN not in span.to_json()
    provider.shutdown()


def test_malformed_url_still_loses_its_query() -> None:
    provider, exporter = scrubbed_provider()
    emit(provider, {"http.url": f"http://[::1/broken?ssn={SSN}"})
    assert attrs_of(only(exporter))["http.url"] == "http://[::1/broken"
    provider.shutdown()


def test_non_string_values_under_scrubbed_keys_are_untouched() -> None:
    provider, exporter = scrubbed_provider()
    emit(provider, {"db.statement": 7, "http.url": ("a", "b"), "url.query": 1})
    attrs = attrs_of(only(exporter))
    assert attrs["db.statement"] == 7
    assert attrs["http.url"] == ("a", "b")
    assert "url.query" not in attrs
    provider.shutdown()


def test_rebuilt_span_keeps_everything_but_the_scrubbed_attributes() -> None:
    raw_exporter = InMemorySpanExporter()
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(raw_exporter))
    provider.add_span_processor(_otel.ScrubbingSpanProcessor(SimpleSpanProcessor(exporter)))
    tracer = provider.get_tracer("test", "1.0")
    with (
        tracer.start_as_current_span("parent"),
        tracer.start_as_current_span(
            "SELECT warehouse", kind=SpanKind.CLIENT, attributes={"db.statement": STATEMENT}
        ) as span,
    ):
        span.add_event("retry", {"attempt": 1})
        span.set_status(Status(StatusCode.ERROR, "boom"))
    raw_child, raw_parent = raw_exporter.get_finished_spans()
    child, parent = exporter.get_finished_spans()
    provider.shutdown()

    assert parent is raw_parent
    assert child is not raw_child
    assert attrs_of(raw_child)["db.statement"] == STATEMENT
    assert attrs_of(child)["db.statement"] == f"sha256:{STATEMENT_SHA256}"
    assert child.name == raw_child.name
    assert child.kind is SpanKind.CLIENT
    assert child.get_span_context() == raw_child.get_span_context()
    assert child.parent == raw_parent.get_span_context()
    assert child.resource is raw_child.resource
    assert child.instrumentation_scope == raw_child.instrumentation_scope
    assert child.status.status_code is StatusCode.ERROR
    assert child.status.description == "boom"
    assert child.events == raw_child.events
    assert child.links == raw_child.links
    assert (child.start_time, child.end_time) == (raw_child.start_time, raw_child.end_time)
    assert child.dropped_attributes == raw_child.dropped_attributes


def test_batch_processor_exports_only_scrubbed_spans() -> None:
    provider, exporter = scrubbed_provider(BatchSpanProcessor)
    emit(provider, {"db.statement": STATEMENT})
    assert provider.force_flush()
    assert attrs_of(only(exporter))["db.statement"] == f"sha256:{STATEMENT_SHA256}"
    provider.shutdown()


def test_processor_delegates_lifecycle_to_the_wrapped_processor() -> None:
    inner = Recording()
    provider = TracerProvider()
    provider.add_span_processor(_otel.ScrubbingSpanProcessor(inner))
    emit(provider, {"db.statement": STATEMENT})
    assert provider.force_flush()
    provider.shutdown()
    assert inner.calls == ["on_start", "on_end", "force_flush", "shutdown"]
    assert attrs_of(inner.ended[0])["db.statement"] == f"sha256:{STATEMENT_SHA256}"


def test_build_hands_the_console_exporter_only_scrubbed_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_otel.OTLP_ENDPOINT_ENV, raising=False)
    out = io.StringIO()
    providers = _otel.build(app="a", team="t", out=out)
    try:
        emit(
            providers.traces,
            {"db.statement": STATEMENT, "http.url": f"http://hr-api.fixture/employees?ssn={SSN}"},
        )
        providers.traces.force_flush()
        printed = out.getvalue()
    finally:
        providers.shutdown()
    (span,) = [json.loads(line) for line in printed.splitlines() if line.strip()]
    assert span["attributes"]["db.statement"] == f"sha256:{STATEMENT_SHA256}"
    assert span["attributes"]["http.url"] == "http://hr-api.fixture/employees"
    assert "E001" not in printed
    assert SSN not in printed


def test_instrumented_query_and_request_leave_no_literal_in_traces(
    write_manifest: ManifestWriter,
    exported: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config.load(write_manifest(connections=("warehouse", "hr-api")))
    with caplog.at_level(logging.INFO, logger="insights.audit"):
        run_query(STATEMENT)
        send_request("/employees", {"ssn": SSN})
    spans = exported.get_finished_spans()
    assert spans
    for span in spans:
        assert "E001" not in span.to_json()
        assert SSN not in span.to_json()

    [query_audit] = [fields_of(r) for r in caplog.records if r.getMessage() == "data.query"]
    assert query_audit["statement_sha256"] == STATEMENT_SHA256
    [query_span] = [
        s for s in spans if str(attrs_of(s).get("db.statement", "")).startswith("sha256:")
    ]
    assert attrs_of(query_span)["db.statement"] == f"sha256:{query_audit['statement_sha256']}"

    [request_audit] = [fields_of(r) for r in caplog.records if r.getMessage() == "data.request"]
    [client_span] = [s for s in spans if s.kind is SpanKind.CLIENT and "http.url" in attrs_of(s)]
    client_attrs = attrs_of(client_span)
    assert client_attrs["http.url"] == "http://hr-api.fixture/employees"
    assert client_attrs["http.url"] == f"http://{request_audit['target']}"
    assert "url.query" not in client_attrs
    assert "url.full" not in client_attrs


def test_server_span_drops_the_request_query_string(
    write_manifest: ManifestWriter, exported: InMemorySpanExporter
) -> None:
    app = web.create_app(manifest=write_manifest())

    @app.get("/open")
    @public
    def open_route() -> dict[str, str]:
        return {"ok": "open"}

    with client_for(app) as client:
        assert client.get("/open", params={"ssn": SSN}).status_code == 200
    spans = exported.get_finished_spans()
    for span in spans:
        assert SSN not in span.to_json()
    [server_span] = [s for s in spans if s.kind is SpanKind.SERVER]
    server_attrs = attrs_of(server_span)
    assert server_attrs["http.url"] == "http://testserver/open"
    assert server_attrs["http.target"] == "/open"
    assert "url.query" not in server_attrs
