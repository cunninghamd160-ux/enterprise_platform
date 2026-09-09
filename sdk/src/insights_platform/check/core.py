import ast
import tomllib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any, Self


@dataclass(frozen=True)
class Violation:
    rule: str
    adr: str
    path: Path
    line: int | None
    message: str

    def __str__(self) -> str:
        where = self.path.as_posix()
        if self.line is not None:
            where = f"{where}:{self.line}"
        return f"violates {self.adr}: {self.message} ({where})"


@dataclass(frozen=True)
class ImportTable:
    aliases: dict[str, str]
    imported: tuple[tuple[str, int], ...]
    modules: tuple[tuple[str, int], ...] = ()

    def resolve(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id)
        if isinstance(node, ast.Attribute):
            base = self.resolve(node.value)
            return None if base is None else f"{base}.{node.attr}"
        return None


EMPTY_IMPORTS = ImportTable({}, ())


def parse_module(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


def import_table(tree: ast.Module, *, package: str | None = None) -> ImportTable:
    aliases: dict[str, str] = {}
    imported: list[tuple[str, int]] = []
    modules: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append((alias.name, node.lineno))
                modules.append((alias.name, node.lineno))
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    root = alias.name.split(".")[0]
                    aliases[root] = root
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_from(node, package)
            if module is None:
                continue
            imported.append((module, node.lineno))
            modules.append((module, node.lineno))
            for alias in node.names:
                if alias.name == "*":
                    continue
                qualified = f"{module}.{alias.name}"
                imported.append((qualified, node.lineno))
                aliases[alias.asname or alias.name] = qualified
    return ImportTable(aliases, tuple(imported), tuple(modules))


def _resolve_from(node: ast.ImportFrom, package: str | None) -> str | None:
    if not node.level:
        return node.module or ""
    # Relative imports are resolved to absolute names so the slice rules can see the edges
    # between an app's own modules. The absolute-prefix rules (httpx, requests, ...) never match a
    # name rooted at the app's package, so their behaviour is unchanged.
    if package is None:
        return None
    parts = package.split(".")
    if node.level > len(parts):
        return None
    base = parts[: len(parts) - node.level + 1]
    return ".".join([*base, node.module] if node.module else base)


@dataclass
class AppContext:
    app_dir: Path
    repo_root: Path
    known_connections: frozenset[str]
    current_scaffold_version: str
    sdk_version: str
    manifest: dict[str, Any] | None
    manifest_error: str | None
    shared: dict[str, Any] = field(default_factory=dict)
    _trees: dict[Path, ast.Module | None] = field(default_factory=dict, init=False, repr=False)
    _imports: dict[Path, ImportTable] = field(default_factory=dict, init=False, repr=False)

    @classmethod
    def load(
        cls,
        app_dir: Path,
        repo_root: Path,
        *,
        known_connections: frozenset[str],
        current_scaffold_version: str,
        sdk_version: str,
        shared: dict[str, Any],
    ) -> Self:
        manifest_path = app_dir / "platform.toml"
        manifest: dict[str, Any] | None = None
        manifest_error: str | None = None
        if manifest_path.is_file():
            try:
                with manifest_path.open("rb") as fh:
                    manifest = tomllib.load(fh)
            except tomllib.TOMLDecodeError as exc:
                manifest_error = str(exc)
        return cls(
            app_dir.resolve(),
            repo_root.resolve(),
            known_connections,
            current_scaffold_version,
            sdk_version,
            manifest,
            manifest_error,
            shared,
        )

    @property
    def manifest_path(self) -> Path:
        return self.app_dir / "platform.toml"

    @cached_property
    def source_files(self) -> tuple[Path, ...]:
        src = self.app_dir / "src"
        return tuple(sorted(src.rglob("*.py"))) if src.is_dir() else ()

    def tree(self, path: Path) -> ast.Module | None:
        if path not in self._trees:
            self._trees[path] = parse_module(path)
        return self._trees[path]

    def imports(self, path: Path) -> ImportTable:
        if path not in self._imports:
            tree = self.tree(path)
            if tree is None:
                self._imports[path] = EMPTY_IMPORTS
            else:
                self._imports[path] = import_table(tree, package=self.package_name(path))
        return self._imports[path]

    def module_name(self, path: Path) -> str | None:
        parts = self._src_parts(path)
        if parts is None:
            return None
        if parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts) or None

    def package_name(self, path: Path) -> str | None:
        parts = self._src_parts(path)
        return None if parts is None else ".".join(parts[:-1]) or None

    def _src_parts(self, path: Path) -> tuple[str, ...] | None:
        try:
            relative = path.relative_to(self.app_dir / "src")
        except ValueError:
            return None
        return relative.with_suffix("").parts

    def calls(self, path: Path) -> Iterator[tuple[str, int]]:
        tree = self.tree(path)
        if tree is None:
            return
        table = self.imports(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                target = table.resolve(node.func)
                if target is not None:
                    yield target, node.lineno

    def rel(self, path: Path) -> Path:
        try:
            return path.relative_to(self.repo_root)
        except ValueError:
            return path


@dataclass(frozen=True)
class Rule:
    name: str
    adr: str
    check: Callable[[AppContext], Iterable[Violation]]
