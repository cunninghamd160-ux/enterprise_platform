from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute

from insights_platform import audit
from insights_platform.auth.sso import Principal

POLICY_ATTR = "__insights_policy__"


@dataclass(frozen=True)
class Policy:
    public: bool = False
    roles: frozenset[str] = frozenset()
    teams: frozenset[str] = frozenset()

    def merge(self, other: "Policy") -> "Policy":
        if self.public or other.public:
            raise ValueError("public cannot be combined with role or team requirements")
        return Policy(roles=self.roles | other.roles, teams=self.teams | other.teams)

    def describe(self) -> str:
        parts = []
        if self.roles:
            parts.append("roles=" + "|".join(sorted(self.roles)))
        if self.teams:
            parts.append("teams=" + "|".join(sorted(self.teams)))
        return " ".join(parts)


def policy_of(endpoint: object) -> Policy | None:
    policy = getattr(endpoint, POLICY_ATTR, None)
    return policy if isinstance(policy, Policy) else None


def _route_path(request: Request, endpoint: object) -> str:
    for route in request.app.routes:
        if isinstance(route, APIRoute) and route.endpoint is endpoint:
            return route.path
    return request.url.path


def enforce(request: Request) -> None:
    endpoint = request.scope.get("endpoint")
    policy = policy_of(endpoint)
    route = _route_path(request, endpoint)
    method = request.method

    if policy is None:
        audit.emit("authz.denied", route=route, method=method, reason="no-policy")
        raise HTTPException(status_code=403)
    if policy.public:
        return

    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        audit.emit("authn.missing", route=route, method=method)
        raise HTTPException(status_code=401)

    role_ok = not policy.roles or bool(policy.roles & principal.roles)
    team_ok = not policy.teams or principal.team in policy.teams
    if not (role_ok and team_ok):
        audit.emit(
            "authz.denied",
            principal=principal.user,
            team=principal.team,
            route=route,
            method=method,
            required=policy.describe(),
        )
        raise HTTPException(status_code=403)
