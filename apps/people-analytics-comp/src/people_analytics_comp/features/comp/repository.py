from collections.abc import Sequence

from sqlalchemy import RowMapping, text

from insights_platform.data import get_engine


async def list_compensation() -> Sequence[RowMapping]:
    async with get_engine("warehouse").connect() as conn:
        result = await conn.execute(
            text(
                "select employee_id, team, base_salary, currency "
                "from compensation order by employee_id"
            )
        )
        return result.mappings().all()
