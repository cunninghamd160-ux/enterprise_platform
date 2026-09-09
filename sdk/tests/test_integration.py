import asyncio
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from insights_platform import config, data, db
from insights_platform.cli import app

# Read at import time: the testing plugin points both variables at SQLite before every test.
_WAREHOUSE_URL = os.environ.get("INSIGHTS_CONN_WAREHOUSE_URL", "")
_OWNED_URL = os.environ.get("INSIGHTS_DB_URL", "")

pytestmark = pytest.mark.integration

type ManifestWriter = Callable[..., Path]

open_session = asynccontextmanager(db.get_session)


@pytest.fixture
def postgres(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if not (_WAREHOUSE_URL.startswith("postgresql") and _OWNED_URL.startswith("postgresql")):
        pytest.skip("INSIGHTS_CONN_WAREHOUSE_URL and INSIGHTS_DB_URL must point at Postgres")
    monkeypatch.setenv("INSIGHTS_CONN_WAREHOUSE_URL", _WAREHOUSE_URL)
    monkeypatch.setenv(db.URL_ENV, _OWNED_URL)
    policy = asyncio.get_event_loop_policy()
    if sys.platform == "win32":
        # psycopg's async connection refuses Windows' default ProactorEventLoop.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    data.reset_clients()
    db.reset()
    yield
    data.reset_clients()
    db.reset()
    asyncio.set_event_loop_policy(policy)


def test_warehouse_reads_from_postgres(postgres: None, write_manifest: ManifestWriter) -> None:
    config.load(write_manifest())
    engine = data.get_engine("warehouse")
    assert engine.url.get_backend_name() == "postgresql"

    async def rows() -> int:
        async with engine.connect() as conn:
            result = await conn.execute(text("select count(*) from compensation"))
            return int(result.scalar_one())

    assert asyncio.run(rows()) == 4


def test_generated_app_migrates_and_writes_on_postgres(
    postgres: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["sdk", "apps/*"]\n', encoding="utf-8"
    )
    (tmp_path / "apps").mkdir()
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    created = runner.invoke(app, ["new", "pg-demo", "--kind", "web", "--team", "demo"])
    assert created.exit_code == 0, created.output
    target = "apps/pg-demo"

    async def write_and_read() -> int:
        async with open_session() as session:
            await session.execute(
                text("insert into records (title) values (:title)"), {"title": "first"}
            )
        async with open_session() as session:
            return int((await session.execute(text("select count(*) from records"))).scalar_one())

    async def drop_version_table() -> None:
        async with db.get_engine().begin() as conn:
            await conn.execute(text("drop table if exists alembic_version"))

    try:
        upgrade = runner.invoke(app, ["db", "upgrade", "--app", target])
        assert upgrade.exit_code == 0, upgrade.output
        config.load(Path(target) / "platform.toml")
        assert db.get_engine().url.get_backend_name() == "postgresql"
        assert asyncio.run(write_and_read()) == 1
        current = runner.invoke(app, ["db", "current", "--app", target])
        assert current.exit_code == 0, current.output
        assert "0001" in current.output
    finally:
        downgrade = runner.invoke(app, ["db", "downgrade", "base", "--app", target])
        assert downgrade.exit_code == 0, downgrade.output
        config.load(Path(target) / "platform.toml")
        asyncio.run(drop_version_table())
