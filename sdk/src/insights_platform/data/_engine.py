import hashlib
from collections.abc import Callable
from typing import Any

import sqlalchemy.ext.asyncio
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy import event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from insights_platform import audit

TIMEOUT_S = 10
_CONNECT_TIMEOUT_ARG = {
    "sqlite": "timeout",
    "postgresql": "connect_timeout",
    "mysql": "connect_timeout",
    "mariadb": "connect_timeout",
}

_instrumentor = SQLAlchemyInstrumentor()


def build_engine(name: str, url: str) -> AsyncEngine:
    parsed = make_url(url)
    connect_args: dict[str, Any] = {}
    if (arg := _CONNECT_TIMEOUT_ARG.get(parsed.get_backend_name())) is not None:
        connect_args[arg] = TIMEOUT_S
    # The instrumentor wraps create_engine and create_async_engine globally on first call and
    # rejects a second call, so instrument once and resolve create_async_engine through the
    # module at call time.
    if not _instrumentor.is_instrumented_by_opentelemetry:
        _instrumentor.instrument()
    engine = sqlalchemy.ext.asyncio.create_async_engine(
        url, pool_pre_ping=True, connect_args=connect_args
    )
    event.listen(engine.sync_engine, "before_cursor_execute", _audit_query(name))
    return engine


def sqlite_file(url: URL) -> str | None:
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        return url.database
    return None


def _audit_query(name: str) -> Callable[..., None]:
    def listener(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        audit.emit(
            "data.query",
            connection=name,
            statement_sha256=hashlib.sha256(statement.encode()).hexdigest(),
        )

    return listener
