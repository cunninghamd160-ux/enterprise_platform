import asyncio
import hashlib
import logging
import sqlite3
from collections.abc import Callable
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Annotated

import pytest
import sqlalchemy.ext.asyncio
from fastapi import Depends
from sqlalchemy import String, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from insights_platform import config, context, db, web
from insights_platform.auth import public
from insights_platform.observability import fields_of
from insights_platform.testing import client_for

type ManifestWriter = Callable[..., Path]

open_session = asynccontextmanager(db.get_session)


class Note(db.Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))


def audit_records(caplog: pytest.LogCaptureFixture, event: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == event]


def table_names() -> set[str]:
    with closing(sqlite3.connect(str(db.get_engine().url.database))) as conn:
        rows = conn.execute("select name from sqlite_master where type = 'table'").fetchall()
    return {row[0] for row in rows}


async def count_notes() -> int:
    async with open_session() as session:
        return int((await session.execute(select(func.count()).select_from(Note))).scalar_one())


def test_get_engine_requires_the_database_to_be_enabled(
    write_manifest: ManifestWriter, monkeypatch: pytest.MonkeyPatch
) -> None:
    config.load(write_manifest())
    monkeypatch.delenv(db.URL_ENV)
    with pytest.raises(db.DatabaseNotEnabledError, match=r"\[database\] enabled = true"):
        db.get_engine()
    db.validate()
    asyncio.run(db.ping())


def test_missing_url_names_the_variable(
    write_manifest: ManifestWriter, monkeypatch: pytest.MonkeyPatch
) -> None:
    config.load(write_manifest(database=True))
    monkeypatch.delenv(db.URL_ENV)
    with pytest.raises(db.MissingDatabaseUrlError, match="INSIGHTS_DB_URL"):
        db.get_engine()
    with pytest.raises(db.MissingDatabaseUrlError):
        db.validate()


def test_validate_creates_the_sqlite_schema_from_the_models(
    write_manifest: ManifestWriter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(db.URL_ENV, f"sqlite+aiosqlite:///{tmp_path.as_posix()}/nested/owned.db")
    config.load(write_manifest(database=True))
    db.validate()
    assert (tmp_path / "nested" / "owned.db").exists()
    assert "notes" in table_names()

    async def add() -> None:
        async with open_session() as session:
            session.add(Note(title="kept"))

    asyncio.run(add())
    db.validate()
    assert asyncio.run(count_notes()) == 1


def test_get_engine_alone_never_touches_the_schema(write_manifest: ManifestWriter) -> None:
    config.load(write_manifest(database=True))
    db.get_engine()
    assert "notes" not in table_names()


def test_owned_engine_carries_timeout_audit_and_instrumentation(
    write_manifest: ManifestWriter, caplog: pytest.LogCaptureFixture
) -> None:
    config.load(write_manifest(database=True))
    context.principal.set("u1")
    context.request_id.set("r1")
    engine = db.get_engine()
    assert engine.url.drivername == "sqlite+aiosqlite"
    assert engine.pool._pre_ping is True
    assert hasattr(sqlalchemy.ext.asyncio.create_async_engine, "__wrapped__")
    statement = "select 'salary 100000'"

    async def query() -> None:
        async with engine.connect() as conn:
            (await conn.execute(text(statement))).all()

    with caplog.at_level(logging.INFO, logger="insights.audit"):
        asyncio.run(query())
    [record] = audit_records(caplog, "data.query")
    fields = fields_of(record)
    assert fields["connection"] == "owned"
    assert fields["principal"] == "u1"
    assert fields["request_id"] == "r1"
    assert fields["statement_sha256"] == hashlib.sha256(statement.encode()).hexdigest()
    assert "salary" not in str(fields)


def test_session_commits_and_audits_writes_without_values(
    write_manifest: ManifestWriter, caplog: pytest.LogCaptureFixture
) -> None:
    config.load(write_manifest(database=True))
    db.validate()
    context.principal.set("dana")

    async def add() -> None:
        async with open_session() as session:
            session.add(Note(title="salary 100000"))

    with caplog.at_level(logging.INFO, logger="insights.audit"):
        asyncio.run(add())
    assert asyncio.run(count_notes()) == 1
    [write] = audit_records(caplog, "data.write")
    fields = fields_of(write)
    assert fields["connection"] == "owned"
    assert fields["table"] == "notes"
    assert fields["rows"] == 1
    assert fields["principal"] == "dana"
    assert "salary" not in str(fields)
    assert audit_records(caplog, "data.query")


def test_session_rolls_back_when_the_block_raises(write_manifest: ManifestWriter) -> None:
    config.load(write_manifest(database=True))
    db.validate()

    async def add_then_fail() -> None:
        async with open_session() as session:
            session.add(Note(title="lost"))
            await session.flush()
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(add_then_fail())
    assert asyncio.run(count_notes()) == 0


def test_write_audit_counts_rows_per_flush(
    write_manifest: ManifestWriter, caplog: pytest.LogCaptureFixture
) -> None:
    config.load(write_manifest(database=True))
    db.validate()

    async def scenario() -> None:
        async with open_session() as session:
            session.add_all([Note(title="a"), Note(title="b")])
            await session.flush()
            first, second = (await session.execute(select(Note).order_by(Note.id))).scalars()
            first.title = "a2"
            await session.flush()
            await session.delete(second)

    with caplog.at_level(logging.INFO, logger="insights.audit"):
        asyncio.run(scenario())
    writes = [fields_of(r) for r in audit_records(caplog, "data.write")]
    assert [(w["table"], w["rows"]) for w in writes] == [("notes", 2), ("notes", 1), ("notes", 1)]


def test_get_session_is_a_fastapi_dependency(write_manifest: ManifestWriter) -> None:
    app = web.create_app(manifest=write_manifest(database=True))

    @app.post("/api/notes")
    @public
    async def add(session: Annotated[AsyncSession, Depends(db.get_session)]) -> dict[str, int]:
        note = Note(title="first")
        session.add(note)
        await session.flush()
        return {"id": note.id}

    @app.get("/api/notes")
    @public
    async def listing(session: Annotated[AsyncSession, Depends(db.get_session)]) -> list[str]:
        return list((await session.execute(select(Note.title))).scalars())

    @app.post("/api/boom")
    @public
    async def boom(session: Annotated[AsyncSession, Depends(db.get_session)]) -> None:
        session.add(Note(title="never"))
        await session.flush()
        raise RuntimeError("boom")

    with client_for(app) as client:
        assert client.post("/api/notes").json() == {"id": 1}
        assert client.get("/api/notes").json() == ["first"]
        with pytest.raises(RuntimeError, match="boom"):
            client.post("/api/boom")
        assert client.get("/api/notes").json() == ["first"]
        assert client.get("/readyz").status_code == 200


def test_ping_selects_one_on_the_owned_database(
    write_manifest: ManifestWriter, caplog: pytest.LogCaptureFixture
) -> None:
    config.load(write_manifest(database=True))
    with caplog.at_level(logging.INFO, logger="insights.audit"):
        asyncio.run(db.ping())
    [record] = audit_records(caplog, "data.query")
    assert fields_of(record)["connection"] == "owned"


def test_reset_disposes_the_engine(write_manifest: ManifestWriter) -> None:
    config.load(write_manifest(database=True))
    db.validate()
    engine = db.get_engine()
    asyncio.run(count_notes())
    assert engine.pool.checkedin() == 1
    db.reset()
    assert engine.pool.checkedin() == 0
    assert db.get_engine() is not engine
