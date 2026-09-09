import json
import sqlite3
from functools import cache
from pathlib import Path
from typing import cast

import httpx
from sqlalchemy.engine import Engine

_DIR = Path(__file__).parent
_SEED_SQL = _DIR / "warehouse.sql"
_HR_API = _DIR / "hr_api.json"


def seed_sqlite(engine: Engine) -> None:
    database = engine.url.database
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    raw = engine.raw_connection()
    try:
        driver = cast(sqlite3.Connection, raw.driver_connection)
        seeded = driver.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'compensation'"
        ).fetchone()
        if seeded is None:
            driver.executescript(_SEED_SQL.read_text(encoding="utf-8"))
            driver.commit()
    finally:
        raw.close()


def hr_api_handler(request: httpx.Request) -> httpx.Response:
    if request.method != "GET":
        return httpx.Response(405)
    parts = request.url.path.strip("/").split("/")
    if parts == ["employees"]:
        return httpx.Response(200, json=_employees())
    if len(parts) == 2 and parts[0] == "employees":
        for employee in _employees():
            if employee["id"] == parts[1]:
                return httpx.Response(200, json=employee)
    return httpx.Response(404, json={"detail": "not found"})


@cache
def _employees() -> list[dict[str, object]]:
    employees: list[dict[str, object]] = json.loads(_HR_API.read_text(encoding="utf-8"))
    return employees
