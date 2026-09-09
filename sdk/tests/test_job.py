import logging
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from insights_platform import config, context, job
from insights_platform.observability import Scalar, fields_of

type ManifestWriter = Callable[..., Path]


def completed(caplog: pytest.LogCaptureFixture) -> tuple[logging.LogRecord, dict[str, Scalar]]:
    [record] = [r for r in caplog.records if r.getMessage() == "job.completed"]
    return record, fields_of(record)


def test_success_returns_zero_and_scopes_context(
    write_manifest: ManifestWriter, caplog: pytest.LogCaptureFixture
) -> None:
    seen: dict[str, str | None] = {}

    def main() -> None:
        seen["principal"] = context.principal.get()
        seen["request_id"] = context.request_id.get()

    with caplog.at_level(logging.INFO, logger="insights.job"):
        assert job.run_job(main, manifest=write_manifest(name="nightly", kind="job")) == 0

    _, fields = completed(caplog)
    assert fields["status"] == "ok"
    assert isinstance(fields["duration_ms"], float)
    assert fields["principal"] == "job:nightly"
    assert re.fullmatch(r"[0-9a-f]{32}", str(fields["trace_id"]))
    assert seen == {"principal": "job:nightly", "request_id": fields["request_id"]}
    assert re.fullmatch(r"[0-9a-f]{32}", str(seen["request_id"]))
    assert context.principal.get() is None
    assert context.request_id.get() is None


def test_failure_returns_one_and_keeps_traceback(
    write_manifest: ManifestWriter, caplog: pytest.LogCaptureFixture
) -> None:
    def main() -> None:
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

    with caplog.at_level(logging.INFO, logger="insights.job"):
        assert job.run_job(lambda: calls.append("ran"), manifest=write_manifest(kind="job")) == 1

    assert calls == []
    assert completed(caplog)[1]["error"] == "MissingCredentialError"


def test_web_manifest_rejected(write_manifest: ManifestWriter) -> None:
    with pytest.raises(config.ConfigError, match="requires kind = 'job'"):
        job.run_job(lambda: None, manifest=write_manifest(kind="web"))


def test_runs_counter(write_manifest: ManifestWriter, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(job, "get_meter", provider.get_meter)

    job.run_job(lambda: None, manifest=write_manifest(kind="job"))

    def fail() -> None:
        raise RuntimeError

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
