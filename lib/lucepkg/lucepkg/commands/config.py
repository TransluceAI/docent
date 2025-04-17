import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import tomlkit
import typer
from luce_lib import config_lib

# pyright: reportUnknownMemberType=false

app = typer.Typer(help="Configuration commands")


@app.command()
def show():
    """Show current configuration as TOML"""
    data = config_lib.load_config()
    doc = tomlkit.document()
    doc.update(data)
    print(tomlkit.dumps(doc))


@app.command()
def json_to_toml():
    """Convert config.json to config.toml and remove the JSON file"""
    config_dir = Path.home() / ".luce"
    json_config = config_dir / "config.json"
    toml_config = config_dir / "config.toml"

    if not json_config.exists():
        print("Error: No config.json found to convert", file=sys.stderr)
        raise typer.Exit(1)

    if toml_config.exists():
        print("Error: config.toml already exists, not overwriting", file=sys.stderr)
        raise typer.Exit(1)

    # Load JSON data
    data = config_lib.load_config()

    # Convert to TOML
    doc = tomlkit.document()
    doc.update(data)

    # Write TOML file
    toml_config.write_text(tomlkit.dumps(doc))

    # Remove JSON file
    json_config.unlink()
    print(f"Converted {json_config} to {toml_config}")


@app.command()
def add_server(
    name: Annotated[str, typer.Argument(help="Name for the server.")],
    hostname: Annotated[
        Optional[str],
        typer.Argument(
            help="Hostname or IP address, if different from NAME",
            show_default="same value as NAME",
        ),
    ] = None,
    remote_path: Annotated[
        str,
        typer.Option("--monorepo-path", "-p", help="Remote path to sync to."),
    ] = "/home/ubuntu/clarity",
    user: Annotated[
        Optional[str], typer.Option("--user", "-u", help="SSH username (optional)")
    ] = None,
    identity_file: Annotated[
        Optional[str], typer.Option("--identity-file", "-i", help="Path to SSH key file")
    ] = None,
):
    """Add a new server to the configuration"""
    config_lib.add_server_to_config(
        name=name,
        hostname=hostname or name,  # Use name as hostname if hostname not provided
        remote_path=remote_path,
        user=user,
        identity_file=identity_file,
    )


@app.command()
def remove_server(
    name: Annotated[
        str,
        typer.Argument(
            help="Name of the server to remove",
            autocompletion=config_lib.complete_server_names,
        ),
    ],
):
    """Remove a server from the configuration"""
    config_lib.remove_server_from_config(name)


@app.command()
def set_artifact_dir(
    path: Annotated[
        str,
        typer.Argument(
            help="Path where build artifacts will be stored (e.g. ~/artifacts or ~/luce-artifacts)"
        ),
    ],
):
    """Set the directory where build artifacts will be stored.

    This directory will be used to store build artifacts that need to be shared
    between different parts of the build process.

    Common values are ~/artifacts or ~/luce-artifacts.
    """
    config_lib.set_artifact_dir(path)


@app.command()
def edit():
    """Open the config file in cursor, vscode, or $EDITOR."""

    # Try to find editor in order: cursor, code, $EDITOR
    editor = None
    for cmd in ["cursor", "code"]:
        if shutil.which(cmd):
            editor = cmd
            break
    if not editor:
        editor = os.environ.get("EDITOR")

    if not editor:
        print(
            "Error: Could not find editor. Please install Cursor or VS Code, "
            "or set the EDITOR environment variable.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    _, config_path = config_lib.get_or_create_toml_doc()

    # Open editor
    print(f"Opening {config_path} in {editor}...")
    subprocess.run([editor, str(config_path)], check=True)
