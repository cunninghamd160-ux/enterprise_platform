from collections.abc import Iterator

from insights_platform.check.core import AppContext, Rule, Violation

_NAME = "no-private-imports"
_ADR = "ADR-0001"


def _is_private_sdk_path(name: str) -> bool:
    parts = name.split(".")
    return parts[0] == "insights_platform" and any(p.startswith("_") for p in parts[1:])


def _check(ctx: AppContext) -> Iterator[Violation]:
    for path in ctx.source_files:
        seen: set[int] = set()
        for name, line in ctx.imports(path).imported:
            if line in seen or not _is_private_sdk_path(name):
                continue
            seen.add(line)
            yield Violation(
                _NAME,
                _ADR,
                ctx.rel(path),
                line,
                f"apps must not import private SDK modules ({name}); "
                "only the public surface is a supported compatibility seam",
            )


RULE = Rule(_NAME, _ADR, _check)
