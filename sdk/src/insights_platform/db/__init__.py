import asyncio
import os
from collections import Counter
from collections.abc import AsyncIterator
from pathlib import Path

import sqlalchemy
from sqlalchemy import Table, event, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Session, UOWTransaction, object_mapper

from insights_platform import audit, config
from insights_platform.data import _engine

__all__ = [
    "CONNECTION",
    "URL_ENV",
    "Base",
    "DatabaseError",
    "DatabaseNotEnabledError",
    "MissingDatabaseUrlError",
    "get_engine",
    "get_session",
    "ping",
    "reset",
    "validate",
]

URL_ENV = "INSIGHTS_DB_URL"
CONNECTION = "owned"


class Base(DeclarativeBase):
    pass


class DatabaseError(Exception):
    pass


class DatabaseNotEnabledError(DatabaseError):
    def __init__(self) -> None:
        super().__init__(
            "the owned database is not enabled; set [database] enabled = true in platform.toml"
        )


class MissingDatabaseUrlError(DatabaseError):
    def __init__(self) -> None:
        super().__init__(
            f"the owned database requires environment variable {URL_ENV}, which is not set"
        )


class _Session(Session):
    pass


_owned: AsyncEngine | None = None
_sessions: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _owned
    if not config.current().database:
        raise DatabaseNotEnabledError()
    if _owned is None:
        url = os.environ.get(URL_ENV)
        if not url:
            raise MissingDatabaseUrlError()
        _owned = _engine.build_engine(CONNECTION, url)
    return _owned


async def get_session() -> AsyncIterator[AsyncSession]:
    global _sessions
    if _sessions is None:
        _sessions = async_sessionmaker(
            get_engine(), sync_session_class=_Session, expire_on_commit=False
        )
    async with _sessions() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        await session.commit()


def validate() -> None:
    if not config.current().database:
        return
    engine = get_engine()
    if (path := _engine.sqlite_file(engine.url)) is not None:
        _create_sqlite_schema(path)


async def ping() -> None:
    if not config.current().database:
        return
    async with get_engine().connect() as conn:
        await conn.execute(text("select 1"))


def reset() -> None:
    global _owned, _sessions
    engine, _owned, _sessions = _owned, None, None
    if engine is not None:
        asyncio.run(engine.dispose())


def _create_sqlite_schema(path: str) -> None:
    # SQLite is the fixture backend, so the schema comes from the models the way the warehouse
    # comes from warehouse.sql; Postgres is only ever migrated by `insights db upgrade`. A sync
    # engine does the DDL because validate() runs inside the app's already-running event loop.
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    engine = sqlalchemy.create_engine(
        URL.create("sqlite", database=path), connect_args={"timeout": _engine.TIMEOUT_S}
    )
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def _audit_flush(session: Session, _flush_context: UOWTransaction) -> None:
    modified = (obj for obj in session.dirty if session.is_modified(obj))
    written = Counter(_table_name(obj) for obj in (*session.new, *session.deleted, *modified))
    for table, rows in sorted(written.items()):
        audit.emit("data.write", connection=CONNECTION, table=table, rows=rows)


def _table_name(obj: object) -> str:
    table = object_mapper(obj).local_table
    return table.name if isinstance(table, Table) else type(obj).__name__


event.listen(_Session, "after_flush", _audit_flush)
