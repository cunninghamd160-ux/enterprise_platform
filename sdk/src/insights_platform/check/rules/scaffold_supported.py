import re
from collections.abc import Iterator

from insights_platform.check.core import AppContext, Rule, Violation

_NAME = "scaffold-supported"
_ADR = "ADR-0001"
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_SUPPORTED_MINORS_BEHIND = 2


def _parse(version: str) -> tuple[int, int, int] | None:
    match = _SEMVER.match(version)
    if match is None:
        return None
    return int(match[1]), int(match[2]), int(match[3])


def _check(ctx: AppContext) -> Iterator[Violation]:
    if ctx.manifest is None:
        return
    app = ctx.manifest.get("app")
    if not isinstance(app, dict):
        return
    version = app.get("scaffold_version")
    if not isinstance(version, str):
        return

    current = _parse(ctx.current_scaffold_version)
    if current is None:
        raise ValueError(f"current scaffold version {ctx.current_scaffold_version!r} is not X.Y.Z")

    path = ctx.rel(ctx.manifest_path)
    parsed = _parse(version)
    if parsed is None:
        yield Violation(_NAME, _ADR, path, None, f"[app].scaffold_version {version!r} is not X.Y.Z")
        return

    if parsed[0] != current[0]:
        yield Violation(
            _NAME,
            _ADR,
            path,
            None,
            f"scaffold_version {version} is from a different major than the current scaffold "
            f"{ctx.current_scaffold_version}; migrate before upgrading",
        )
    elif parsed[1] < current[1] - _SUPPORTED_MINORS_BEHIND:
        yield Violation(
            _NAME,
            _ADR,
            path,
            None,
            f"scaffold_version {version} is more than {_SUPPORTED_MINORS_BEHIND} minors behind "
            f"the current scaffold {ctx.current_scaffold_version}; regenerate or migrate",
        )


RULE = Rule(_NAME, _ADR, _check)
