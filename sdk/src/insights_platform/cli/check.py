from pathlib import Path
from typing import Annotated

import typer

from insights_platform import __version__
from insights_platform.check import discover_apps, run
from insights_platform.cli._repo import RepoRootNotFoundError, find_repo_root
from insights_platform.data.registry import KNOWN_CONNECTIONS


def check(
    paths: Annotated[
        list[Path] | None,
        typer.Argument(help="App directories to check. Defaults to every app under <repo>/apps."),
    ] = None,
) -> None:
    missing = [p for p in paths or [] if not p.is_dir()]
    if missing:
        for p in missing:
            typer.echo(f"error: {p} is not a directory", err=True)
        raise typer.Exit(code=1)
    try:
        root = find_repo_root(paths[0] if paths else None)
    except RepoRootNotFoundError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    app_dirs = [p.resolve() for p in paths] if paths else discover_apps(root)
    violations = run(
        app_dirs,
        repo_root=root,
        known_connections=frozenset(KNOWN_CONNECTIONS),
        current_scaffold_version=__version__,
        sdk_version=__version__,
    )
    for violation in violations:
        typer.echo(str(violation))
    if violations:
        raise typer.Exit(code=1)
    typer.echo(f"{len(app_dirs)} app(s) checked, no violations")
