from collections.abc import Iterator

from insights_platform.check.core import AppContext, Rule, Violation

_NAME = "no-raw-alembic"
_ADR = "ADR-0003"
_BANNED = "alembic"


def _check(ctx: AppContext) -> Iterator[Violation]:
    for path in ctx.source_files:
        seen: set[int] = set()
        for name, line in ctx.imports(path).imported:
            if (name != _BANNED and not name.startswith(f"{_BANNED}.")) or line in seen:
                continue
            seen.add(line)
            yield Violation(
                _NAME,
                _ADR,
                ctx.rel(path),
                line,
                "apps must not import alembic; migrations live under migrations/ and run through "
                "insights db (revision, upgrade, current), which owns the connection and the "
                "Alembic configuration",
            )


RULE = Rule(_NAME, _ADR, _check)
