from people_analytics_dash.main import app

from insights_platform.testing import client_for, headers_for


def test_root_is_public() -> None:
    with client_for(app) as client:
        assert client.get("/api").json() == {"app": "people-analytics-dash"}


def test_records_requires_the_owning_team() -> None:
    with client_for(app) as client:
        assert client.get("/api/records").status_code == 401
        other = headers_for("someone", team="not-people-analytics")
        assert client.get("/api/records", headers=other).status_code == 403
        owner = headers_for("someone", team="people-analytics")
        response = client.get("/api/records", headers=owner)
        assert response.status_code == 200
        assert response.json()


def test_healthz_needs_no_headers() -> None:
    with client_for(app) as client:
        assert client.get("/healthz").status_code == 200
