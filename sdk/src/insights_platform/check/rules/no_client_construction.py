from collections.abc import Iterator

from insights_platform.check.core import AppContext, Rule, Violation

_NAME = "no-client-construction"
_ADR = "ADR-0005"
_HTTPX_SHORTCUTS = ("get", "post", "put", "patch", "delete", "head", "options", "request", "stream")
_BANNED_CALLS = frozenset(
    {
        "sqlalchemy.create_engine",
        "sqlalchemy.engine.create_engine",
        "sqlalchemy.ext.asyncio.create_async_engine",
        "httpx.Client",
        "httpx.AsyncClient",
        *(f"httpx.{fn}" for fn in _HTTPX_SHORTCUTS),
    }
)


def _check(ctx: AppContext) -> Iterator[Violation]:
    for path in ctx.source_files:
        for target, line in ctx.calls(path):
            if target in _BANNED_CALLS:
                yield Violation(
                    _NAME,
                    _ADR,
                    ctx.rel(path),
                    line,
                    f"apps must not construct connection clients ({target}); "
                    "insights_platform.data.get_connection() attaches the credentials, "
                    "timeouts, and audit hook every data access must carry",
                )


RULE = Rule(_NAME, _ADR, _check)
