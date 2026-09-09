from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from insights_platform import cache, context, data, db, observability
from insights_platform.auth.sso import ROLES_HEADER, TEAM_HEADER, USER_HEADER

__all__ = ["client_for", "headers_for", "insights_fixture_env"]

_CONTEXT_VARS = (context.app, context.team, context.principal, context.request_id)


def headers_for(user: str, *, team: str, roles: Iterable[str] = ()) -> dict[str, str]:
    headers = {USER_HEADER: user, TEAM_HEADER: team}
    role_list = list(roles)
    if role_list:
        headers[ROLES_HEADER] = ",".join(role_list)
    return headers


@contextmanager
def client_for(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def insights_fixture_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(
        "INSIGHTS_CONN_WAREHOUSE_URL",
        f"sqlite+aiosqlite:///{(tmp_path / 'warehouse.db').as_posix()}",
    )
    monkeypatch.setenv("INSIGHTS_CONN_HR_API_URL", "http://hr-api.fixture")
    monkeypatch.setenv("INSIGHTS_CONN_HR_API_TOKEN", "fixture-token")
    monkeypatch.setenv(db.URL_ENV, f"sqlite+aiosqlite:///{(tmp_path / 'owned.db').as_posix()}")
    monkeypatch.delenv(cache.CACHE_URL_ENV, raising=False)
    data.reset_clients()
    db.reset()
    cache.reset_cache()
    snapshot = [(var, var.get()) for var in _CONTEXT_VARS]
    try:
        yield
    finally:
        data.reset_clients()
        db.reset()
        cache.reset_cache()
        for var, value in snapshot:
            var.set(value)


def pytest_sessionfinish() -> None:
    # Console exporters hold the stdout pytest captured; shutting down here flushes them while
    # that stream is still open instead of at interpreter exit, when it is not.
    observability.shutdown()
