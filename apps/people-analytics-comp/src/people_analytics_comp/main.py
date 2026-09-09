from insights_platform.auth import public
from insights_platform.web import create_app

from .features import comp

app = create_app()
app.include_router(comp.router, prefix="/api")


@app.get("/api")
@public
async def root() -> dict[str, str]:
    return {"app": "people-analytics-comp"}
