from pathlib import Path
from typing import NamedTuple

from insights_platform.check.core import AppContext

FEATURES = "features"
INIT = "__init__"


class Slice(NamedTuple):
    package: str
    feature: str
    layer: str


def slice_of(ctx: AppContext, path: Path) -> Slice | None:
    module = ctx.module_name(path)
    if module is None:
        return None
    parts = module.split(".")
    if path.name == "__init__.py":
        parts.append(INIT)
    return slice_of_name(parts)


def slice_of_name(parts: list[str]) -> Slice | None:
    # The layer is the first segment after the feature, so <feature>/<helper>/x.py is <helper>.
    if len(parts) < 4 or parts[1] != FEATURES:
        return None
    return Slice(parts[0], parts[2], parts[3])
