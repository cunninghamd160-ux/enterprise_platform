import hashlib
import os
from collections.abc import Callable
from typing import Any

import httpx
import sqlalchemy
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url

from insights_platform import audit, config, context
from insights_platform.data import _fixtures
from insights_platform.data.registry import KNOWN_CONNECTIONS, ConnectionSpec

type Connection = Engine | httpx.Client

_TIMEOUT_S = 10
_CONNECT_TIMEOUT_ARG = {
    "sqlite": "timeout",
    "postgresql": "connect_timeout",
    "mysql": "connect_timeout",
    "mariadb": "connect_timeout",
}

_clients: dict[str, Connection] = {}
_sqlalchemy_instrumentor = SQLAlchemyInstrumentor()


class DataConnectionError(Exception):
    pass


class ConnectionNotDeclaredError(DataConnectionError):
    def __init__(self, name: str, declared: tuple[str, ...]) -> None:
        super().__init__(
            f"connection {name!r} is not declared in platform.toml "
            f"(declared: {', '.join(declared) or 'none'})"
        )


class UnknownConnectionError(DataConnectionError):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"connection {name!r} is not in the platform registry "
            f"(known: {', '.join(sorted(KNOWN_CONNECTIONS))})"
        )


class MissingCredentialError(DataConnectionError):
    def __init__(self, name: str, var: str) -> None:
        super().__init__(
            f"connection {name!r} requires environment variable {var}, which is not set"
        )


class WrongConnectionKindError(DataConnectionError):
    def __init__(self, name: str, expected: str) -> None:
        super().__init__(f"connection {name!r} is not a {expected} connection")


def get_connection(name: str) -> Connection:
    declared = config.current().connections
    if name not in declared:
        raise ConnectionNotDeclaredError(name, declared)
    if name not in _clients:
        _clients[name] = _build(_spec(name))
    return _clients[name]


def get_engine(name: str) -> Engine:
    connection = get_connection(name)
    if not isinstance(connection, Engine):
        raise WrongConnectionKindError(name, "sql")
    return connection


def get_http_client(name: str) -> httpx.Client:
    connection = get_connection(name)
    if not isinstance(connection, httpx.Client):
        raise WrongConnectionKindError(name, "http")
    return connection


def validate_connections() -> None:
    for name in config.current().connections:
        get_connection(name)


def _spec(name: str) -> ConnectionSpec:
    try:
        return KNOWN_CONNECTIONS[name]
    except KeyError:
        raise UnknownConnectionError(name) from None


def _credentials(spec: ConnectionSpec) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in spec.keys:
        var = spec.env_var(key)
        value = os.environ.get(var)
        if not value:
            raise MissingCredentialError(spec.name, var)
        values[key] = value
    return values


def _build(spec: ConnectionSpec) -> Connection:
    credentials = _credentials(spec)
    if spec.kind == "sql":
        return _build_engine(spec.name, credentials["url"])
    return _build_http_client(spec.name, credentials["url"], credentials["token"])


def _build_engine(name: str, url: str) -> Engine:
    backend = make_url(url).get_backend_name()
    connect_args: dict[str, Any] = {}
    if (arg := _CONNECT_TIMEOUT_ARG.get(backend)) is not None:
        connect_args[arg] = _TIMEOUT_S
    # The instrumentor wraps sqlalchemy.create_engine globally on first call and rejects a second
    # call, so instrument once and resolve create_engine through the module at call time.
    if not _sqlalchemy_instrumentor.is_instrumented_by_opentelemetry:
        _sqlalchemy_instrumentor.instrument()
    engine = sqlalchemy.create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    if backend == "sqlite":
        _fixtures.seed_sqlite(engine)
    event.listen(engine, "before_cursor_execute", _audit_query(name))
    return engine


def _build_http_client(name: str, url: str, token: str) -> httpx.Client:
    is_fixture = httpx.URL(url).host.endswith(".fixture")
    client = httpx.Client(
        base_url=url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(_TIMEOUT_S),
        transport=httpx.MockTransport(_fixtures.hr_api_handler) if is_fixture else None,
        event_hooks={"request": [_audit_request(name)]},
    )
    HTTPXClientInstrumentor.instrument_client(client)
    return client


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
            principal=context.principal.get(),
            request_id=context.request_id.get(),
            statement_sha256=hashlib.sha256(statement.encode()).hexdigest(),
        )

    return listener


def _audit_request(name: str) -> Callable[[httpx.Request], None]:
    def hook(request: httpx.Request) -> None:
        audit.emit(
            "data.request",
            connection=name,
            method=request.method,
            target=f"{request.url.host}{request.url.path}",
            principal=context.principal.get(),
            request_id=context.request_id.get(),
        )

    return hook
