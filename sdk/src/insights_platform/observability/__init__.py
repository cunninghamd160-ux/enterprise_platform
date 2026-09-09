import logging

type Scalar = str | int | float | bool | None


class Logger:
    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    def _emit(self, level: int, event: str, fields: dict[str, Scalar]) -> None:
        self._log.log(level, event, extra={"fields": fields})

    def info(self, event: str, **fields: Scalar) -> None:
        self._emit(logging.INFO, event, fields)

    def warning(self, event: str, **fields: Scalar) -> None:
        self._emit(logging.WARNING, event, fields)

    def error(self, event: str, **fields: Scalar) -> None:
        self._emit(logging.ERROR, event, fields)


def get_logger(name: str) -> Logger:
    return Logger(name)
