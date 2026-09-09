from insights_platform.observability import Logger, Scalar

STREAM_FIELD = "insights.stream"
STREAM = "audit"

_log = Logger("insights.audit")


def emit(event: str, **fields: Scalar) -> None:
    _log.info(event, **{**fields, STREAM_FIELD: STREAM})
