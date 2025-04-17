import os
import subprocess
import sys
from typing import Annotated

import typer
from luce_lib import monorepo_util

app = typer.Typer(help="UV package installer commands")


@app.command()
def install():
    """Install the uv package installer"""
    try:
        # Try to run uv --version
        result = subprocess.run(["uv", "--version"], capture_output=True, text=True, check=True)
        print(f"uv is already installed (version {result.stdout.strip()})")
        return

    except subprocess.CalledProcessError:
        # This shouldn't ever happen, because `luce` in `activate_luce.sh` should handle this
        # command whenever `uv` is not installed.
        print(
            "Error: This command should be run via the shell function. Did you "
            "remember to `source lib/lucepkg/scripts/activate_luce.sh` and run via `luce`?",
            file=sys.stderr,
        )
        raise typer.Exit(1)


@app.command()
def lock_all(
    check: Annotated[
        bool,
        typer.Option(
            help=(
                "Asserts that the uv.lock would remain unchanged after a resolution. If the "
                "lockfile is missing or needs to be updated, exit with an error."
            ),
        ),
    ] = False,
):
    """Run uv lock in all Python package directories."""
    monorepo_root = monorepo_util.find_monorepo_root()

    # Unset VIRTUAL_ENV to silence uv warnings
    os.environ.pop("VIRTUAL_ENV", None)

    # Packages with virtual environments to check
    package_dirs = [
        monorepo_root,
        monorepo_root / "lib/lucepkg",
    ]

    # Directories to search for subpackages in
    search_dirs = [
        monorepo_root / "envs",
    ]
    for dir_path in search_dirs:
        if not dir_path.is_dir():
            continue
        print(f"\nSearching {dir_path.relative_to(monorepo_root)}/")
        for package_dir in dir_path.iterdir():
            if package_dir.is_dir() and monorepo_util.has_pyproject_toml(package_dir):
                package_dirs.append(package_dir)

    cmd = ["uv", "lock"]
    if check:
        cmd.append("--check")

    for package_dir in package_dirs:
        if package_dir == monorepo_root:
            name = "monorepo root"
        else:
            name = package_dir.relative_to(monorepo_root)

        if check:
            print(f"== Checking lockfile for {name} ==")
        else:
            print(f"== Updating lockfile for {name} ==")
        try:
            subprocess.run(cmd, cwd=package_dir, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to lock {package_dir}: {e}", file=sys.stderr)
            raise typer.Exit(1)

    if check:
        print("All uv.lock files are up-to-date.")
    else:
        print("Updated all uv.lock files.")
