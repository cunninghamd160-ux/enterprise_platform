import logging

import pytest

import insights_platform
from insights_platform import audit
from insights_platform.observability import get_logger


def test_version() -> None:
    assert insights_platform.__version__


def test_logger_carries_fields(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="insights.test"):
        get_logger("insights.test").info("hello", app="demo", count=1)
    assert caplog.records[0].fields == {"app": "demo", "count": 1}


def test_audit_emits(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="insights.audit"):
        audit.emit("authz.denied", principal="u1", route="/comp")
    assert caplog.records[0].getMessage() == "authz.denied"
