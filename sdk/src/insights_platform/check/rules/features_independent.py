from collections.abc import Iterator

from insights_platform.check.core import AppContext, Rule, Violation
from insights_platform.check.rules._slices import FEATURES, slice_of, slice_of_name

_NAME = "features-independent"
_ADR = "ADR-0003"


def _check(ctx: AppContext) -> Iterator[Violation]:
    for path in ctx.source_files:
        own = slice_of(ctx, path)
        if own is None:
            continue
        seen: set[tuple[int, str]] = set()
        for module, line in ctx.imports(path).modules:
            target = slice_of_name(module.split("."))
            if target is None or target.package != own.package or target.feature == own.feature:
                continue
            if (line, module) in seen:
                continue
            seen.add((line, module))
            surface = f"{own.package}.{FEATURES}.{target.feature}"
            yield Violation(
                _NAME,
                _ADR,
                ctx.rel(path),
                line,
                f"feature {own.feature!r} must import feature {target.feature!r} only as "
                f"{surface}, the package whose __init__ is its public surface; "
                f"{module} reaches inside it",
            )


RULE = Rule(_NAME, _ADR, _check)
