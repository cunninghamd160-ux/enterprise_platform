import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from packaging.version import Version

from insights_platform import __version__
from insights_platform.cli._repo import RepoRootNotFoundError, find_repo_root

_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
_SUFFIX = ".tmpl"
_FRONTEND_DIR = "frontend"
_NO_FRONTEND = ".no-frontend"


class Kind(StrEnum):
    web = "web"
    job = "job"


class ScaffoldError(Exception):
    pass


def sdk_pin(version: str) -> str:
    """Range admitting the current SDK release and its patches, per ADR-0001."""
    parsed = Version(version)
    return f">={parsed.major}.{parsed.minor},<{parsed.major}.{parsed.minor + 1}"


def scaffold(name: str, kind: Kind, team: str, dest: Path, *, frontend: bool = True) -> Path:
    if not _NAME.match(name):
        raise ScaffoldError(f"{name!r} is not kebab-case (expected ^[a-z][a-z0-9-]*$)")
    target = dest / name
    if target.exists():
        raise ScaffoldError(f"{target} already exists")
    substitutions = {
        "__NAME__": name,
        "__PKG__": name.replace("-", "_"),
        "__TEAM__": team,
        "__SCAFFOLD_VERSION__": __version__,
        "__SDK_PIN__": sdk_pin(__version__),
    }
    for relative, path in _select(_TEMPLATES / kind.value, frontend=frontend).items():
        out = target / _substitute(relative, substitutions)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            _substitute(path.read_text(encoding="utf-8"), substitutions),
            encoding="utf-8",
            newline="\n",
        )
    return target


def _select(source: Path, *, frontend: bool) -> dict[str, Path]:
    """Output path -> template file. Token substitution has no conditionals (ADR-0002), so
    `--no-frontend` drops `frontend/**` and lets `<file>.no-frontend.tmpl` replace `<file>.tmpl`."""
    selected: dict[str, Path] = {}
    variants: dict[str, Path] = {}
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        relative = path.relative_to(source).as_posix()
        out = relative.removesuffix(_SUFFIX)
        if out.endswith(_NO_FRONTEND):
            variants[out.removesuffix(_NO_FRONTEND)] = path
        elif frontend or not relative.startswith(f"{_FRONTEND_DIR}/"):
            selected[out] = path
    if not frontend:
        selected.update(variants)
    return selected


def _substitute(text: str, substitutions: dict[str, str]) -> str:
    for placeholder, value in substitutions.items():
        text = text.replace(placeholder, value)
    return text


def new(
    name: Annotated[
        str, typer.Argument(help="App name in kebab-case, e.g. people-analytics-comp.")
    ],
    kind: Annotated[Kind, typer.Option("--kind", help="Template to generate from.")],
    team: Annotated[
        str | None, typer.Option("--team", help="Owning team. Defaults to NAME.")
    ] = None,
    dest: Annotated[
        Path | None, typer.Option("--dest", help="Parent directory. Defaults to <repo>/apps.")
    ] = None,
    no_frontend: Annotated[
        bool,
        typer.Option(
            "--no-frontend",
            help="Web apps only: generate an API-only app with no frontend/. Jobs never have one.",
        ),
    ] = False,
) -> None:
    try:
        parent = dest if dest is not None else find_repo_root() / "apps"
        created = scaffold(name, kind, team or name, parent, frontend=not no_frontend)
    except (RepoRootNotFoundError, ScaffoldError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    shown = _display(created)
    typer.echo(f"Created {shown}")
    typer.echo("Next:")
    typer.echo("  uv sync")
    typer.echo(f"  uv run pytest {shown}")
    typer.echo(f"  uv run insights check {shown}")
    if (created / _FRONTEND_DIR).is_dir():
        typer.echo(f"  npm ci --prefix {shown}/frontend")
        typer.echo(f"  npm run dev --prefix {shown}/frontend")


def _display(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()
