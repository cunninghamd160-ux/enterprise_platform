from collections.abc import Iterator
from pathlib import Path

from insights_platform.check.core import (
    AppContext,
    ImportTable,
    Rule,
    Violation,
    import_table,
    parse_module,
)

_NAME = "apps-independent"
_ADR = "ADR-0004"
_SDK_IMPORTS_KEY = "apps-independent.sdk-imports"


def _app_packages(apps_dir: Path) -> dict[str, Path]:
    packages: dict[str, Path] = {}
    if not apps_dir.is_dir():
        return packages
    for app in sorted(apps_dir.iterdir()):
        src = app / "src"
        if not src.is_dir():
            continue
        for pkg in sorted(src.iterdir()):
            if pkg.is_dir() and pkg.name.isidentifier():
                packages[pkg.name] = app.resolve()
    return packages


def _sdk_imports(ctx: AppContext) -> dict[Path, ImportTable]:
    cached: dict[Path, ImportTable] | None = ctx.shared.get(_SDK_IMPORTS_KEY)
    if cached is None:
        cached = {}
        sdk_src = ctx.repo_root / "sdk" / "src"
        if sdk_src.is_dir():
            for path in sorted(sdk_src.rglob("*.py")):
                tree = parse_module(path)
                if tree is not None:
                    cached[path] = import_table(tree)
        ctx.shared[_SDK_IMPORTS_KEY] = cached
    return cached


def _check(ctx: AppContext) -> Iterator[Violation]:
    packages = _app_packages(ctx.repo_root / "apps")
    own = {pkg for pkg, app in packages.items() if app == ctx.app_dir}
    foreign = {pkg: app for pkg, app in packages.items() if app != ctx.app_dir}

    for path in ctx.source_files:
        seen: set[tuple[int, str]] = set()
        for name, line in ctx.imports(path).imported:
            root = name.split(".")[0]
            if root not in foreign or (line, root) in seen:
                continue
            seen.add((line, root))
            yield Violation(
                _NAME,
                _ADR,
                ctx.rel(path),
                line,
                f"apps must not import each other; {root} belongs to apps/{foreign[root].name}",
            )

    for sdk_path, table in _sdk_imports(ctx).items():
        seen = set()
        for name, line in table.imported:
            root = name.split(".")[0]
            if root not in own or (line, root) in seen:
                continue
            seen.add((line, root))
            yield Violation(
                _NAME,
                _ADR,
                ctx.rel(sdk_path),
                line,
                f"the SDK must not import app packages; {root} belongs to apps/{ctx.app_dir.name}",
            )


RULE = Rule(_NAME, _ADR, _check)
