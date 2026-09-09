from contextvars import ContextVar

app: ContextVar[str | None] = ContextVar("insights.app", default=None)
team: ContextVar[str | None] = ContextVar("insights.team", default=None)
principal: ContextVar[str | None] = ContextVar("insights.principal", default=None)
request_id: ContextVar[str | None] = ContextVar("insights.request_id", default=None)
