import asyncio
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from insights_platform import config, db

db_app = typer.Typer(
    no_args_is_help=True,
    help="Migrate the app's owned database. Wraps Alembic; apps never touch alembic.ini.",
)

_APP = typer.Option(
    "--app",
    help="App directory. Defaults to the app whose platform.toml is found upward from here.",
)


@db_app.command()
def revision(
    message: Annotated[str, typer.Option("-m", "--message", help="What the migration does.")],
    autogenerate: Annotated[
        bool,
        typer.Option("--autogenerate", help="Diff the models against the database first."),
    ] = False,
    app: Annotated[Path | None, _APP] = None,
) -> None:
    _run(app, lambda cfg: command.revision(cfg, message=message, autogenerate=autogenerate))


@db_app.command()
def upgrade(
    revision: Annotated[str, typer.Argument(help="Target revision.")] = "head",
    app: Annotated[Path | None, _APP] = None,
) -> None:
    _run(app, lambda cfg: command.upgrade(cfg, revision))


@db_app.command()
def downgrade(
    revision: Annotated[str, typer.Argument(help="Target revision, e.g. -1 or base.")],
    app: Annotated[Path | None, _APP] = None,
) -> None:
    _run(app, lambda cfg: command.downgrade(cfg, revision))


@db_app.command()
def current(app: Annotated[Path | None, _APP] = None) -> None:
    _run(app, lambda cfg: command.current(cfg))


def _run(app_dir: Path | None, action: Callable[[Config], object]) -> None:
    if sys.platform == "win32":
        # psycopg's async connection refuses Windows' default ProactorEventLoop.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        action(_alembic_config(app_dir))
    except (config.ConfigError, db.DatabaseError, CommandError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except SQLAlchemyError as exc:
        # The driver's message names the problem; the statement and its parameters do not.
        detail = exc.orig if isinstance(exc, DBAPIError) else exc
        typer.echo(f"error: {type(exc).__name__}: {detail}", err=True)
        raise typer.Exit(code=1) from None


def _alembic_config(app_dir: Path | None) -> Config:
    manifest = config.locate((app_dir or Path.cwd()).resolve())
    if not config.load(manifest).database:
        raise db.DatabaseNotEnabledError()
    if not os.environ.get(db.URL_ENV):
        raise db.MissingDatabaseUrlError()
    migrations = manifest.parent / "migrations"
    if not migrations.is_dir():
        raise config.ConfigError(f"{migrations} not found; insights new generates it for web apps")
    _show_alembic_progress()
    alembic = Config(stdout=typer.get_text_stream("stdout"))
    alembic.set_main_option("script_location", str(migrations))
    alembic.set_main_option("prepend_sys_path", str(manifest.parent / "src"))
    # Without a separator Alembic splits the path on ":" and breaks a C:\ path.
    alembic.set_main_option("path_separator", "os")
    return alembic


class _EchoHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        typer.echo(record.getMessage(), err=True)


def _show_alembic_progress() -> None:
    logger = logging.getLogger("alembic")
    if not any(isinstance(h, _EchoHandler) for h in logger.handlers):
        logger.addHandler(_EchoHandler())
        logger.setLevel(logging.INFO)
