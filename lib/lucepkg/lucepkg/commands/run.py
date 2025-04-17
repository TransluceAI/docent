import pathlib
import re
import shlex
import signal
import subprocess
import sys
from typing import Annotated, Any, Dict

import tomlkit
import typer

app = typer.Typer(help="Script execution commands")


def parse_script_metadata(script_path: pathlib.Path) -> Dict[str, Any]:
    """
    Parse PEP 723 script metadata from a Python script.

    Args:
        script_path: Path to the script file

    Returns:
        Dictionary containing parsed metadata
    """
    if not script_path.exists():
        print(f"Error: Script '{script_path}' not found.", file=sys.stderr)
        raise typer.Exit(1)

    metadata_str = ""
    in_metadata_block = False

    with open(script_path, "r", encoding="utf-8") as f:
        for line in f:
            if not in_metadata_block and re.match(r"^#\s*///\s*(script|pyproject).*$", line):
                in_metadata_block = True
                continue
            elif in_metadata_block and re.match(r"^#\s*///\s*$", line):
                in_metadata_block = False
                break
            elif in_metadata_block:
                # Remove leading '# ' from metadata lines
                metadata_line = re.sub(r"^#\s*", "", line)
                metadata_str += metadata_line

    if not metadata_str:
        return {}

    try:
        return dict(tomlkit.parse(metadata_str))
    except Exception as e:
        print(f"Error: Failed to parse script metadata: {e}", file=sys.stderr)
        raise typer.Exit(1)


@app.command(
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "allow_interspersed_args": False,
        "help_option_names": [],  # Disable the built-in help option
    }
)
def run(
    ctx: typer.Context,
    script_path: str,
    cmd_prefix: Annotated[
        list[str],
        typer.Option(
            "--cmd-prefix",
            "-p",
            help="Command prefix or interpreter to use to run the script in the environment.",
        ),
    ] = ["python"],
):
    """
    Execute a script with the appropriate environment setup.

    Parses PEP 723 metadata from the script and configures the environment
    according to [tool.luce.run] table before executing the script.

    By default executes the script with the Python interpreter from the environment. You can use
    -p (or --cmd-prefix) to use a different interpreter or inject args before the script path, e.g.
    `luce run -p marimo -p edit script.py --watch` will run `marimo edit script.py --watch` in the
    environment.

    Any additional arguments after the script path will be forwarded to the script.
    """
    # Special case: if script_path is exactly "--help" and there are no args
    # This means the user wrote: luce run --help
    if script_path == "--help" and not ctx.args:
        print(ctx.get_help())
        raise typer.Exit()
    script_path_obj = pathlib.Path(script_path).absolute()

    # Parse script metadata
    metadata = parse_script_metadata(script_path_obj)
    luce_config = metadata.get("tool", {}).get("luce", {}).get("run", {})

    if not luce_config:
        print(
            "Error: No [tool.luce.run] table found in script metadata. Please add one (it can be"
            " empty), e.g.:\n\n# /// script\n# [tool.luce.run]\n# ///",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    # Extract configuration options
    env_name = luce_config.get("env", "base")
    groups = luce_config.get("groups", [])
    extra_deps = luce_config.get("extra_deps", [])

    # Prepare uv run command
    uv_cmd = ["uv", "run"]

    if luce_config.get("isolated", False):
        uv_cmd.append("--isolated")

    # Add environment configuration
    from luce_lib import monorepo_util

    monorepo_root = monorepo_util.find_monorepo_root()

    if env_name == "base":
        env_dir = monorepo_root
    else:
        env_dir = monorepo_root / "envs" / env_name

    if not env_dir.is_dir():
        print(f"Error: Environment '{env_name}' not found at {env_dir}.", file=sys.stderr)
        raise typer.Exit(1)

    uv_cmd.extend(["--project", str(env_dir)])

    # Add groups configuration
    if groups:
        for group in groups:
            uv_cmd.extend(["--group", group])

    # Add extra_deps configuration
    if extra_deps:
        for dep in extra_deps:
            uv_cmd.extend(["--with", dep])

    # Add the script path as the command to run, wrapped in the prefix as needed.
    uv_cmd.extend(cmd_prefix)
    uv_cmd.extend([str(script_path_obj)])

    # Add any extra arguments after the script path
    if ctx.args:
        uv_cmd.extend(ctx.args)

    # Print the command for debugging
    cmd_str = " ".join(shlex.quote(arg) for arg in uv_cmd)
    print(f"Running: {cmd_str}")

    # Execute the command but ignore SIGINT
    process = subprocess.Popen(uv_cmd)
    # Mask SIGINT (Ctrl+C) while the subprocess is running
    prev_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        return_code = process.wait()
        sys.exit(return_code)
    finally:
        # Restore the previous signal handler
        signal.signal(signal.SIGINT, prev_handler)
