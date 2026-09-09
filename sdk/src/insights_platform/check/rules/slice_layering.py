from collections.abc import Iterator

from insights_platform.check.core import AppContext, Rule, Violation
from insights_platform.check.rules._slices import INIT, Slice, slice_of, slice_of_name

_NAME = "slice-layering"
_ADR = "ADR-0003"
_LAYERS = ("router", "service", "repository", "models", "schemas")
_ALLOWED: dict[str, frozenset[str]] = {
    "router": frozenset({"service", "schemas"}),
    "service": frozenset({"repository", "models", "schemas"}),
    "repository": frozenset({"models"}),
    "models": frozenset(),
    "schemas": frozenset(),
}
_LEAVES = frozenset({"models", "schemas"})


def _permits(importer: str, target: str) -> bool:
    if importer in (INIT, target) or target == INIT:
        return True
    if importer in _LEAVES:
        return False
    if importer in _ALLOWED:
        return target in _ALLOWED[importer] or target not in _ALLOWED
    return target in _LEAVES


def _describe(importer: str) -> str:
    if importer in _LEAVES:
        return f"{importer} imports nothing inside its feature"
    if importer in _ALLOWED:
        allowed = ", ".join(layer for layer in _LAYERS if layer in _ALLOWED[importer])
        return f"{importer} may import {allowed} or a helper module"
    return f"{importer} is a helper module and may import only models or schemas"


def _check(ctx: AppContext) -> Iterator[Violation]:
    for path in ctx.source_files:
        own = slice_of(ctx, path)
        if own is None:
            continue
        seen: set[tuple[int, str]] = set()
        for name, line in ctx.imports(path).imported:
            target = slice_of_name(name.split("."))
            if target is None or target[:2] != own[:2] or (line, target.layer) in seen:
                continue
            seen.add((line, target.layer))
            if _permits(own.layer, target.layer):
                continue
            yield Violation(_NAME, _ADR, ctx.rel(path), line, _message(own, target))


def _message(own: Slice, target: Slice) -> str:
    return (
        f"{own.layer} must not import {target.layer} inside feature {own.feature!r}; "
        f"{_describe(own.layer)}"
    )


RULE = Rule(_NAME, _ADR, _check)
