import typer
from luce_lib import config_lib, monorepo_util

app = typer.Typer(help="Get various paths and configuration values")


@app.command()
def artifact_dir() -> None:
    """Print the artifact directory path."""
    try:
        artifact_dir = config_lib.get_artifact_dir()
        print(str(artifact_dir))
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def monorepo_root() -> None:
    """Print the monorepo root path."""
    try:
        root = monorepo_util.find_monorepo_root()
        print(str(root))
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
