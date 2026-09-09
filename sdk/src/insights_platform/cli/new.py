import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from insights_platform import __version__
from insights_platform.cli._repo import RepoRootNotFoundError, find_repo_root

_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
_SUFFIX = ".tmpl"


class Kind(StrEnum):
    web = "web"
    job = "job"


class ScaffoldError(Exception):
    pass


def scaffold(name: str, kind: Kind, team: str, dest: Path) -> Path:
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
    }
    source = _TEMPLATES / kind.value
    for path in sorted(source.rglob("*")):
        if path.is_dir():
            continue
        relative = _substitute(path.relative_to(source).as_posix(), substitutions)
        out = target / relative.removesuffix(_SUFFIX)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            _substitute(path.read_text(encoding="utf-8"), substitutions),
            encoding="utf-8",
            newline="\n",
        )
    return target


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
) -> None:
    try:
        parent = dest if dest is not None else find_repo_root() / "apps"
        created = scaffold(name, kind, team or name, parent)
    except (RepoRootNotFoundError, ScaffoldError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    shown = _display(created)
    typer.echo(f"Created {shown}")
    typer.echo("Next:")
    typer.echo("  uv sync")
    typer.echo(f"  uv run pytest {shown}")
    typer.echo(f"  uv run insights check {shown}")


def _display(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()
