from typing import Any

from sqlalchemy import text

from insights_platform.auth import public, require_team
from insights_platform.data import get_engine
from insights_platform.web import create_app

app = create_app()


@app.get("/api")
@public
async def root() -> dict[str, str]:
    return {"app": "people-analytics-dash"}


@app.get("/api/records")
@require_team("people-analytics")
async def records() -> list[dict[str, Any]]:
    async with get_engine("warehouse").connect() as conn:
        result = await conn.execute(
            text("select team, month, count from headcount order by month, team")
        )
        return [dict(row) for row in result.mappings()]
