import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy import text

from insights_platform import config, context, data, job
from insights_platform.observability import Scalar, fields_of

type ManifestWriter = Callable[..., Path]


def completed(caplog: pytest.LogCaptureFixture) -> tuple[logging.LogRecord, dict[str, Scalar]]:
    [record] = [r for r in caplog.records if r.getMessage() == "job.completed"]
    return record, fields_of(record)


async def noop() -> None:
    pass


async def fail() -> None:
    raise RuntimeError


def test_success_returns_zero_and_scopes_context(
    write_manifest: ManifestWriter, caplog: pytest.LogCaptureFixture
) -> None:
    seen: dict[str, str | None] = {}

    async def main() -> None:
        seen["principal"] = context.principal.get()
        seen["request_id"] = context.request_id.get()
        seen["trace_id"] = format(trace.get_current_span().get_span_context().trace_id, "032x")

    with caplog.at_level(logging.INFO, logger="insights.job"):
        assert job.run_job(main, manifest=write_manifest(name="nightly", kind="job")) == 0

    _, fields = completed(caplog)
    assert fields["status"] == "ok"
    assert isinstance(fields["duration_ms"], float)
    assert fields["principal"] == "job:nightly"
    assert re.fullmatch(r"[0-9a-f]{32}", str(fields["trace_id"]))
    assert seen == {
        "principal": "job:nightly",
        "request_id": fields["request_id"],
        "trace_id": fields["trace_id"],
    }
    assert re.fullmatch(r"[0-9a-f]{32}", str(seen["request_id"]))
    assert context.principal.get() is None
    assert context.request_id.get() is None


def test_main_awaits_a_declared_connection(write_manifest: ManifestWriter) -> None:
    rows: list[object] = []

    async def main() -> None:
        async with data.get_engine("warehouse").connect() as conn:
            result = await conn.execute(text("select count(*) from compensation"))
            rows.extend(result.all())

    assert job.run_job(main, manifest=write_manifest(kind="job")) == 0
    assert rows


def test_failure_returns_one_and_keeps_traceback(
    write_manifest: ManifestWriter, caplog: pytest.LogCaptureFixture
) -> None:
    async def main() -> None:
        raise ValueError("boom")

    with caplog.at_level(logging.INFO, logger="insights.job"):
        assert job.run_job(main, manifest=write_manifest(kind="job")) == 1

    record, fields = completed(caplog)
    assert fields["status"] == "failed"
    assert fields["error"] == "ValueError"
    assert record.exc_info is not None
    assert record.exc_info[0] is ValueError


def test_missing_credential_fails_before_fn_runs(
    write_manifest: ManifestWriter,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("INSIGHTS_CONN_WAREHOUSE_URL")
    calls: list[str] = []

    async def main() -> None:
        calls.append("ran")

    with caplog.at_level(logging.INFO, logger="insights.job"):
        assert job.run_job(main, manifest=write_manifest(kind="job")) == 1

    assert calls == []
    assert completed(caplog)[1]["error"] == "MissingCredentialError"


def test_web_manifest_rejected(write_manifest: ManifestWriter) -> None:
    with pytest.raises(config.ConfigError, match="requires kind = 'job'"):
        job.run_job(noop, manifest=write_manifest(kind="web"))


def test_runs_counter(write_manifest: ManifestWriter, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(job, "get_meter", provider.get_meter)

    job.run_job(noop, manifest=write_manifest(kind="job"))
    job.run_job(fail, manifest=write_manifest(kind="job"))

    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None
    points = {
        dict(point.attributes or {})["status"]: int(point.value)
        for resource_metrics in metrics_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        if metric.name == "insights.job.runs"
        for point in metric.data.data_points
    }
    assert points == {"ok": 1, "failed": 1}


def test_owned_database_is_validated_before_fn_runs(
    write_manifest: ManifestWriter,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("INSIGHTS_DB_URL")
    calls: list[str] = []

    async def main() -> None:
        calls.append("ran")

    with caplog.at_level(logging.INFO, logger="insights.job"):
        assert job.run_job(main, manifest=write_manifest(kind="job", database=True)) == 1

    assert calls == []
    assert completed(caplog)[1]["error"] == "MissingDatabaseUrlError"


def test_owned_sqlite_database_exists_when_main_runs(write_manifest: ManifestWriter) -> None:
    seen: list[bool] = []

    async def main() -> None:
        seen.append(
            Path(os.environ["INSIGHTS_DB_URL"].removeprefix("sqlite+aiosqlite:///")).exists()
        )

    assert job.run_job(main, manifest=write_manifest(kind="job", database=True)) == 0
    assert seen == [True]
