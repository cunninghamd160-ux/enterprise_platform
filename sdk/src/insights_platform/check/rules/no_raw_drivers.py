from collections.abc import Iterator

from insights_platform.check.core import AppContext, Rule, Violation

_NAME = "no-raw-drivers"
_ADR = "ADR-0003"
_BANNED = ("psycopg", "psycopg2", "asyncpg", "requests", "urllib.request")


def _check(ctx: AppContext) -> Iterator[Violation]:
    for path in ctx.source_files:
        seen: set[tuple[int, str]] = set()
        for name, line in ctx.imports(path).imported:
            hit = next((b for b in _BANNED if name == b or name.startswith(f"{b}.")), None)
            if hit is None or (line, hit) in seen:
                continue
            seen.add((line, hit))
            yield Violation(
                _NAME,
                _ADR,
                ctx.rel(path),
                line,
                f"apps must not import {hit}; declare the connection in platform.toml and "
                "obtain a client from insights_platform.data.get_connection()",
            )


RULE = Rule(_NAME, _ADR, _check)
