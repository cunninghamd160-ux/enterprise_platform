import asyncio
import os
from collections.abc import Awaitable, Callable

import httpx
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from insights_platform import audit, config
from insights_platform.data import _engine, _fixtures
from insights_platform.data.registry import KNOWN_CONNECTIONS, ConnectionSpec

type Connection = AsyncEngine | httpx.AsyncClient

_TIMEOUT_S = _engine.TIMEOUT_S

_clients: dict[str, Connection] = {}


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


def get_engine(name: str) -> AsyncEngine:
    connection = get_connection(name)
    if not isinstance(connection, AsyncEngine):
        raise WrongConnectionKindError(name, "sql")
    return connection


def get_http_client(name: str) -> httpx.AsyncClient:
    connection = get_connection(name)
    if not isinstance(connection, httpx.AsyncClient):
        raise WrongConnectionKindError(name, "http")
    return connection


def validate_connections() -> None:
    for name in config.current().connections:
        get_connection(name)


async def ping_connections() -> None:
    for name in config.current().connections:
        connection = get_connection(name)
        if isinstance(connection, AsyncEngine):
            async with connection.connect() as conn:
                await conn.execute(text("select 1"))
        else:
            # Any status, 404 or 405 included, proves the host answers; only transport errors
            # and timeouts propagate.
            await connection.head("/")


def reset_clients() -> None:
    clients = list(_clients.values())
    _clients.clear()
    if clients:
        # aiosqlite closes through its own awaitable, so sync_engine.dispose() outside a
        # greenlet leaks the connection; a short-lived loop is the sync-safe way to close.
        asyncio.run(_close(clients))


async def _close(clients: list[Connection]) -> None:
    for client in clients:
        if isinstance(client, AsyncEngine):
            await client.dispose()
        else:
            await client.aclose()


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


def _build_engine(name: str, url: str) -> AsyncEngine:
    engine = _engine.build_engine(name, url)
    if (path := _engine.sqlite_file(engine.url)) is not None:
        _fixtures.seed_sqlite(path, timeout=_TIMEOUT_S)
    return engine


def _build_http_client(name: str, url: str, token: str) -> httpx.AsyncClient:
    is_fixture = httpx.URL(url).host.endswith(".fixture")
    client = httpx.AsyncClient(
        base_url=url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(_TIMEOUT_S),
        transport=httpx.MockTransport(_fixtures.hr_api_handler) if is_fixture else None,
        event_hooks={"request": [_audit_request(name)]},
    )
    HTTPXClientInstrumentor.instrument_client(client)
    return client


def _audit_request(name: str) -> Callable[[httpx.Request], Awaitable[None]]:
    async def hook(request: httpx.Request) -> None:
        audit.emit(
            "data.request",
            connection=name,
            method=request.method,
            target=f"{request.url.host}{request.url.path}",
        )

    return hook
