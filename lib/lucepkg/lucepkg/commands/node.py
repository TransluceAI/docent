import subprocess
from typing import Annotated

import typer
from luce_lib import monorepo_util

app = typer.Typer(help="Node.js related commands")


@app.command()
def install(
    version: Annotated[
        str, typer.Option("--version", "-v", help="Node.js version to install")
    ] = "22",
):
    """Install Node.js using nvm"""
    monorepo_root = monorepo_util.find_monorepo_root()
    install_script = monorepo_root / "lib/lucepkg/scripts/commands/install_node.sh"
    subprocess.run(["bash", str(install_script), version], check=True)
