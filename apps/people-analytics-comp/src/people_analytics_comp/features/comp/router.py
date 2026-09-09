from fastapi import APIRouter

from insights_platform.auth import require_team

from . import service
from .schemas import CompensationRow

router = APIRouter()


@router.get("/comp")
@require_team("people-analytics")
async def compensation() -> list[CompensationRow]:
    return await service.list_compensation()
