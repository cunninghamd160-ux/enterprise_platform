from typing import Any

from sqlalchemy import text

from insights_platform.auth import public, require_team
from insights_platform.data import get_engine
from insights_platform.web import create_app

app = create_app()


@app.get("/")
@public
def root() -> dict[str, str]:
    return {"app": "people-analytics-comp"}


@app.get("/comp")
@require_team("people-analytics")
def compensation() -> list[dict[str, Any]]:
    with get_engine("warehouse").connect() as conn:
        rows = conn.execute(
            text(
                "select employee_id, team, base_salary, currency "
                "from compensation order by employee_id"
            )
        )
        return [dict(row) for row in rows.mappings()]
