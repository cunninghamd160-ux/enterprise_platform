from collections.abc import Iterator

import pytest

from insights_platform import context


@pytest.fixture(autouse=True)
def _reset_request_context() -> Iterator[None]:
    yield
    for var in (context.app, context.team, context.principal, context.request_id):
        var.set(None)
