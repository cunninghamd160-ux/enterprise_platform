from collections.abc import Iterator

from insights_platform.check.core import AppContext, Rule, Violation

_NAME = "no-raw-drivers"
_ADR = "ADR-0003"
_DATA_SEAM = (
    "declare the connection in platform.toml and obtain a client from "
    "insights_platform.data.get_connection()"
)
_CACHE_SEAM = (
    "obtain the cache from insights_platform.cache.get_cache(), which attaches the app "
    "namespace, timeouts, audit hook, and instrumentation every cache access must carry"
)
_BANNED: dict[str, str] = {
    "psycopg": _DATA_SEAM,
    "psycopg2": _DATA_SEAM,
    "asyncpg": _DATA_SEAM,
    "aiosqlite": _DATA_SEAM,
    "requests": _DATA_SEAM,
    "urllib.request": _DATA_SEAM,
    "redis": _CACHE_SEAM,
    "aioredis": _CACHE_SEAM,
    "memcache": _CACHE_SEAM,
}


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
                f"apps must not import {hit}; {_BANNED[hit]}",
            )


RULE = Rule(_NAME, _ADR, _check)
