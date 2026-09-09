import logging
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from insights_platform import context
from insights_platform.auth import (
    Principal,
    UnprotectedRouteError,
    check_routes,
    get_principal,
    install,
    public,
    require_role,
    require_team,
)
from insights_platform.auth.authz import Policy
from insights_platform.auth.sso import principal_from_headers

PA = {
    "X-Insights-User": "dana",
    "X-Insights-Team": "people-analytics",
    "X-Insights-Roles": "analyst, viewer",
}
FIN = {"X-Insights-User": "sam", "X-Insights-Team": "finance", "X-Insights-Roles": "viewer"}
PA_ADMIN = {
    "X-Insights-User": "lee",
    "X-Insights-Team": "people-analytics",
    "X-Insights-Roles": "admin",
}


def build_app() -> FastAPI:
    app = FastAPI()
    install(app)

    @app.get("/open")
    @public
    def open_route() -> dict[str, str]:
        return {"ok": "public"}

    @app.get("/comp")
    @require_team("people-analytics")
    def comp() -> dict[str, str]:
        return {"ok": "comp"}

    @app.get("/analyst")
    @require_role("analyst")
    def analyst() -> dict[str, str]:
        return {"ok": "analyst"}

    @app.get("/admin-comp")
    @require_team("people-analytics")
    @require_role("admin")
    def admin_comp() -> dict[str, str]:
        return {"ok": "admin-comp"}

    @app.get("/whoami")
    @require_role("viewer", "admin")
    def whoami(principal: Annotated[Principal, Depends(get_principal)]) -> dict[str, object]:
        return {"user": principal.user, "team": principal.team, "roles": sorted(principal.roles)}

    @app.get("/ctx")
    @require_role("viewer")
    def ctx() -> dict[str, str | None]:
        return {"principal": context.principal.get(), "request_id": context.request_id.get()}

    return app


@pytest.fixture
def app() -> FastAPI:
    return build_app()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def audit_log(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger="insights.audit")
    return caplog


def audit_events(caplog: pytest.LogCaptureFixture) -> list[tuple[str, dict[str, object]]]:
    return [(r.getMessage(), r.fields) for r in caplog.records if r.name == "insights.audit"]


def test_public_route_without_headers(client: TestClient) -> None:
    assert client.get("/open").status_code == 200


def test_protected_route_without_headers_is_401_and_audited(
    client: TestClient, audit_log: pytest.LogCaptureFixture
) -> None:
    assert client.get("/comp").status_code == 401
    assert audit_events(audit_log) == [("authn.missing", {"route": "/comp", "method": "GET"})]


def test_wrong_team_is_403_and_audited(
    client: TestClient, audit_log: pytest.LogCaptureFixture
) -> None:
    assert client.get("/comp", headers=FIN).status_code == 403
    [(event, fields)] = audit_events(audit_log)
    assert event == "authz.denied"
    assert fields == {
        "principal": "sam",
        "team": "finance",
        "route": "/comp",
        "method": "GET",
        "required": "teams=people-analytics",
    }


def test_right_team_is_200(client: TestClient, audit_log: pytest.LogCaptureFixture) -> None:
    assert client.get("/comp", headers=PA).status_code == 200
    assert audit_events(audit_log) == []


def test_require_role(client: TestClient) -> None:
    assert client.get("/analyst", headers=PA).status_code == 200
    assert client.get("/analyst", headers=FIN).status_code == 403


def test_stacked_markers_require_both_dimensions(client: TestClient) -> None:
    assert client.get("/admin-comp", headers=PA).status_code == 403
    assert client.get("/admin-comp", headers=FIN).status_code == 403
    assert client.get("/admin-comp", headers=PA_ADMIN).status_code == 200


def test_role_is_any_of(client: TestClient) -> None:
    assert client.get("/whoami", headers=FIN).status_code == 200
    assert client.get("/whoami", headers=PA_ADMIN).status_code == 200


def test_public_cannot_combine_with_requirements() -> None:
    with pytest.raises(ValueError, match="public"):
        Policy(public=True).merge(Policy(roles=frozenset({"x"})))


def test_unmarked_route_is_denied_and_detected(
    app: FastAPI, audit_log: pytest.LogCaptureFixture
) -> None:
    @app.get("/unmarked")
    def unmarked() -> dict[str, str]:
        return {"ok": "never"}

    assert TestClient(app).get("/unmarked", headers=PA).status_code == 403
    assert audit_events(audit_log) == [
        ("authz.denied", {"route": "/unmarked", "method": "GET", "reason": "no-policy"})
    ]
    with pytest.raises(UnprotectedRouteError, match=r"GET /unmarked: no authorization marker"):
        check_routes(app)


def test_route_added_before_install_is_detected() -> None:
    app = FastAPI()

    @app.get("/early")
    @public
    def early() -> dict[str, str]:
        return {"ok": "early"}

    install(app)
    with pytest.raises(UnprotectedRouteError, match=r"GET /early: registered before install\(\)"):
        check_routes(app)


def test_check_routes_passes_on_compliant_app(app: FastAPI) -> None:
    check_routes(app)


def test_install_is_idempotent(app: FastAPI) -> None:
    install(app)
    install(app)
    enforce_deps = [d for d in app.router.dependencies if d.dependency.__name__ == "enforce"]
    assert len(enforce_deps) == 1
    assert sum(m.cls.__name__ == "SSOMiddleware" for m in app.user_middleware) == 1


def test_context_is_set_during_request_and_reset_after(client: TestClient) -> None:
    body = client.get("/ctx", headers=PA).json()
    assert body["principal"] == "dana"
    assert body["request_id"]
    assert context.principal.get() is None
    assert context.request_id.get() is None


def test_supplied_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/ctx", headers={**PA, "X-Request-ID": "abc123"})
    assert response.headers["X-Request-ID"] == "abc123"
    assert response.json()["request_id"] == "abc123"


def test_request_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/open")
    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    int(request_id, 16)


def test_get_principal_dependency(client: TestClient) -> None:
    assert client.get("/whoami", headers=PA).json() == {
        "user": "dana",
        "team": "people-analytics",
        "roles": ["analyst", "viewer"],
    }


def test_principal_from_headers_parsing() -> None:
    assert principal_from_headers({}) is None
    assert principal_from_headers({"X-Insights-User": "  "}) is None
    principal = principal_from_headers(
        {"X-Insights-User": " dana ", "X-Insights-Roles": " a , ,b "}
    )
    assert principal == Principal(user="dana", team="", roles=frozenset({"a", "b"}))
