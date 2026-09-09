from collections.abc import Iterable
from pathlib import Path
from typing import Any

from insights_platform.check.core import AppContext, ImportTable, Rule, Violation
from insights_platform.check.rules import RULES

__all__ = ["RULES", "AppContext", "ImportTable", "Rule", "Violation", "discover_apps", "run"]


def discover_apps(repo_root: Path) -> list[Path]:
    apps = repo_root / "apps"
    if not apps.is_dir():
        return []
    return sorted(d for d in apps.iterdir() if d.is_dir() and (d / "platform.toml").is_file())


def run(
    app_dirs: Iterable[Path],
    *,
    repo_root: Path,
    known_connections: frozenset[str],
    current_scaffold_version: str,
    sdk_version: str,
) -> list[Violation]:
    shared: dict[str, Any] = {}
    violations: list[Violation] = []
    for app_dir in app_dirs:
        ctx = AppContext.load(
            app_dir,
            repo_root,
            known_connections=known_connections,
            current_scaffold_version=current_scaffold_version,
            sdk_version=sdk_version,
            shared=shared,
        )
        for rule in RULES:
            violations.extend(rule.check(ctx))
    return violations
