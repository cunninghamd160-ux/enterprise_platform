import tomllib
from collections.abc import Iterator
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from insights_platform.check.core import AppContext, Rule, Violation

_NAME = "sdk-pin-declared"
_ADR = "ADR-0001"
_SDK = canonicalize_name("insights-platform")


def _dependencies(data: dict[str, Any]) -> list[str]:
    project = data.get("project")
    if not isinstance(project, dict):
        return []
    declared = project.get("dependencies")
    if not isinstance(declared, list):
        return []
    return [d for d in declared if isinstance(d, str)]


def _check(ctx: AppContext) -> Iterator[Violation]:
    path = ctx.app_dir / "pyproject.toml"
    rel = ctx.rel(path)

    if not path.is_file():
        yield Violation(
            _NAME, _ADR, rel, None, "pyproject.toml is missing; an app declares the SDK it pins"
        )
        return
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        yield Violation(_NAME, _ADR, rel, None, f"pyproject.toml is not valid TOML: {exc}")
        return

    for raw in _dependencies(data):
        try:
            requirement = Requirement(raw)
        except InvalidRequirement:
            continue
        if canonicalize_name(requirement.name) != _SDK:
            continue
        if not requirement.specifier:
            yield Violation(
                _NAME,
                _ADR,
                rel,
                None,
                f"depends on {raw!r} without a version specifier; pin the approved SDK release "
                "range, because uv drops the constraint for a workspace source and cannot",
            )
            return
        try:
            current = Version(ctx.sdk_version)
        except InvalidVersion:
            raise ValueError(f"SDK version {ctx.sdk_version!r} is not a valid version") from None
        if current not in requirement.specifier:
            yield Violation(
                _NAME,
                _ADR,
                rel,
                None,
                f"pins insights-platform{requirement.specifier}, which excludes the current SDK "
                f"release {ctx.sdk_version}",
            )
        return

    yield Violation(
        _NAME, _ADR, rel, None, "declares no dependency on insights-platform in [project]"
    )


RULE = Rule(_NAME, _ADR, _check)
