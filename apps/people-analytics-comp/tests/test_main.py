from people_analytics_comp.main import app

from insights_platform.testing import client_for, headers_for


def test_root_is_public() -> None:
    with client_for(app) as client:
        assert client.get("/api").json() == {"app": "people-analytics-comp"}


def test_comp_requires_the_people_analytics_team() -> None:
    with client_for(app) as client:
        assert client.get("/api/comp").status_code == 401
        other = headers_for("someone", team="finance")
        assert client.get("/api/comp", headers=other).status_code == 403
        owner = headers_for("someone", team="people-analytics")
        response = client.get("/api/comp", headers=owner)
        assert response.status_code == 200
        assert {"employee_id", "team", "base_salary", "currency"} <= set(response.json()[0])


def test_slash_belongs_to_the_frontend_and_this_app_has_none() -> None:
    with client_for(app) as client:
        assert client.get("/").status_code == 404


def test_healthz_needs_no_headers() -> None:
    with client_for(app) as client:
        assert client.get("/healthz").status_code == 200
