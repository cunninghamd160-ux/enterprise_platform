from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from insights_platform.auth.authz import POLICY_ATTR, Policy, enforce, policy_of
from insights_platform.auth.sso import Principal, SSOMiddleware

__all__ = [
    "Principal",
    "UnprotectedRouteError",
    "check_routes",
    "get_principal",
    "install",
    "public",
    "require_role",
    "require_team",
]


class UnprotectedRouteError(RuntimeError):
    pass


def _mark[F: Callable[..., object]](fn: F, policy: Policy) -> F:
    existing = policy_of(fn)
    setattr(fn, POLICY_ATTR, existing.merge(policy) if existing else policy)
    return fn


def require_role[F: Callable[..., object]](*roles: str) -> Callable[[F], F]:
    policy = Policy(roles=frozenset(roles))

    def decorate(fn: F) -> F:
        return _mark(fn, policy)

    return decorate


def require_team[F: Callable[..., object]](*teams: str) -> Callable[[F], F]:
    policy = Policy(teams=frozenset(teams))

    def decorate(fn: F) -> F:
        return _mark(fn, policy)

    return decorate


def public[F: Callable[..., object]](fn: F) -> F:
    return _mark(fn, Policy(public=True))


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(status_code=401)
    return principal


def install(app: FastAPI) -> None:
    # Must run before any route is added: router-level dependencies are copied into each route at
    # registration time, so earlier routes never see `enforce`. check_routes() catches that case.
    if getattr(app.state, "insights_auth_installed", False):
        return
    app.add_middleware(SSOMiddleware)
    app.router.dependencies.append(Depends(enforce))
    app.state.insights_auth_installed = True


def _has_enforce(dependant: Dependant) -> bool:
    return any(dep.call is enforce or _has_enforce(dep) for dep in dependant.dependencies)


def check_routes(app: FastAPI) -> None:
    offenders: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        label = f"{','.join(sorted(route.methods or []))} {route.path}"
        if policy_of(route.endpoint) is None:
            offenders.append(f"{label}: no authorization marker (require_role/require_team/public)")
        if not _has_enforce(route.dependant):
            offenders.append(f"{label}: registered before install(); enforcement not attached")
    if offenders:
        raise UnprotectedRouteError("unprotected routes:\n  " + "\n  ".join(offenders))
