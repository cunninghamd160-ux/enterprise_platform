from collections.abc import Iterator

from insights_platform.check.core import AppContext, Rule, Violation

_NAME = "use-create-app"
_ADR = "ADR-0003"
_BANNED_CALLS = frozenset({"fastapi.FastAPI", "fastapi.applications.FastAPI"})


def _check(ctx: AppContext) -> Iterator[Violation]:
    for path in ctx.source_files:
        for target, line in ctx.calls(path):
            if target in _BANNED_CALLS:
                yield Violation(
                    _NAME,
                    _ADR,
                    ctx.rel(path),
                    line,
                    "apps must not construct FastAPI() directly; "
                    "insights_platform.web.create_app() installs the auth middleware, "
                    "health routes, and the boot-time route check",
                )


RULE = Rule(_NAME, _ADR, _check)
