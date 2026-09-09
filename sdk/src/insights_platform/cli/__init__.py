import typer

from insights_platform.cli.check import check
from insights_platform.cli.db import db_app
from insights_platform.cli.new import new

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Insights Hub platform CLI.")
app.command()(new)
app.command()(check)
app.add_typer(db_app, name="db")
