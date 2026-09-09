from collections.abc import Mapping
from dataclasses import dataclass
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from insights_platform import context

USER_HEADER = "X-Insights-User"
TEAM_HEADER = "X-Insights-Team"
ROLES_HEADER = "X-Insights-Roles"
REQUEST_ID_HEADER = "X-Request-ID"


@dataclass(frozen=True)
class Principal:
    user: str
    team: str
    roles: frozenset[str]


def principal_from_headers(headers: Mapping[str, str]) -> Principal | None:
    # Stub SSO: trusted headers stand in for the IdP; a real IdP replaces only this function.
    user = headers.get(USER_HEADER, "").strip()
    if not user:
        return None
    team = headers.get(TEAM_HEADER, "").strip()
    roles = frozenset(r.strip() for r in headers.get(ROLES_HEADER, "").split(",") if r.strip())
    return Principal(user=user, team=team, roles=roles)


class SSOMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        principal = principal_from_headers(headers)
        request_id = headers.get(REQUEST_ID_HEADER, "").strip() or uuid4().hex

        state = scope.setdefault("state", {})
        state["principal"] = principal
        state["request_id"] = request_id

        principal_token = context.principal.set(principal.user if principal else None)
        request_id_token = context.request_id.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            context.principal.reset(principal_token)
            context.request_id.reset(request_id_token)
