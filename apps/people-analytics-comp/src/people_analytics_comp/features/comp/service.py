from . import repository
from .schemas import CompensationRow


async def list_compensation() -> list[CompensationRow]:
    rows = await repository.list_compensation()
    return [CompensationRow.model_validate(dict(row)) for row in rows]
