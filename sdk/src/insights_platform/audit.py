from insights_platform.observability import Scalar, get_logger

_log = get_logger("insights.audit")


def emit(event: str, **fields: Scalar) -> None:
    _log.info(event, **fields)
