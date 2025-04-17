import json
import pathlib
import shutil
import subprocess
import sys
from enum import Enum
from typing import Annotated, Optional

import rich
import typer
from luce_lib import artifact_lib, config_lib

app = typer.Typer(help="Commands for managing artifacts (model checkpoints, datasets, etc.)")


def _get_local_artifact_info(path: pathlib.Path) -> str:
    """Get a brief description of a local artifact.

    Args:
        path: Path to local artifact

    Returns:
        Description string
    """
    if path.is_file():
        size = path.stat().st_size
        return f"File, {size} bytes"
    else:
        # List immediate contents if it's a directory
        items = list(path.iterdir())
        return f"Directory with {len(items)} items"


class RemoveTarget(str, Enum):
    """Where to remove artifacts from."""

    LOCAL = "local"
    S3 = "s3"
    BOTH = "both"


def _complete_local_artifacts(incomplete: str) -> list[str]:
    """Complete artifact paths from local artifact directory.

    Args:
        incomplete: Partial artifact path to complete

    Returns:
        List of matching artifact paths. Directories end with /
    """
    try:
        data = config_lib.load_config()
        artifact_dir = pathlib.Path(data["artifact_dir"]).expanduser()
    except (KeyError, typer.Exit):
        return []

    # Split into parent and current part
    parent = pathlib.Path(incomplete).parent
    search_dir = artifact_dir / parent

    try:
        completions: list[str] = []
        for path in search_dir.iterdir():
            name = str(path.relative_to(artifact_dir))
            if name.startswith(incomplete):
                if path.is_dir():
                    completions.append(f"{name}/")
                else:
                    completions.append(name)
        return completions
    except FileNotFoundError:
        return []


def _complete_s3_artifacts(incomplete: str) -> list[str]:
    """Complete artifact paths from S3 bucket.

    Args:
        incomplete: Partial artifact path to complete

    Returns:
        List of matching artifact paths. Directories end with /
    """
    # Split into parent and current part
    parent = str(pathlib.Path(incomplete).parent)
    if parent == ".":
        prefix = ""
    else:
        prefix = f"{parent}/"

    try:
        result = subprocess.run(
            [
                "aws",
                "s3api",
                "list-objects-v2",
                "--bucket",
                artifact_lib.ARTIFACT_BUCKET,
                "--prefix",
                prefix,
                "--delimiter",
                "/",  # Only get one level
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        response = json.loads(result.stdout)

        completions: list[str] = []

        # Add common prefixes (directories)
        for prefix_obj in response.get("CommonPrefixes", []):
            name = prefix_obj["Prefix"]
            if name.startswith(incomplete):
                completions.append(name)

        # Add objects (files)
        for obj in response.get("Contents", []):
            name = obj["Key"]
            if name.startswith(incomplete) and not name.endswith("/"):
                completions.append(name)

        return completions
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []


def _complete_both_artifacts(incomplete: str) -> list[tuple[str, str]]:
    """Complete artifact paths from both local and S3, with source annotations.

    Args:
        incomplete: Partial artifact path to complete

    Returns:
        List of (path, source) tuples. Paths may end with / for directories.
        Source is one of: "local", "s3", or "both"
    """
    local_paths = set(_complete_local_artifacts(incomplete))
    s3_paths = set(_complete_s3_artifacts(incomplete))

    completions: list[tuple[str, str]] = []

    # Add paths that exist in both
    for path in local_paths & s3_paths:
        completions.append((path, "synced"))

    # Add local-only paths
    for path in local_paths - s3_paths:
        completions.append((path, "on local machine"))

    # Add s3-only paths
    for path in s3_paths - local_paths:
        completions.append((path, "on s3"))

    return sorted(completions)


def _complete_rm_artifacts(ctx: typer.Context, incomplete: str) -> list[str]:
    """Complete artifact paths for rm command.

    Args:
        ctx: Typer context
        incomplete: Partial artifact path to complete

    Returns:
        List of matching paths
    """
    # For simplicity, only complete local paths in "both" mode
    if ctx.params.get("target") == RemoveTarget.S3:
        return _complete_s3_artifacts(incomplete)
    return _complete_local_artifacts(incomplete)


@app.command()
def download(
    artifact_key: Annotated[
        str,
        typer.Argument(
            help="Path to the artifact from the artifacts root",
            autocompletion=_complete_s3_artifacts,
        ),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Force download even if local files exist and would be modified",
        ),
    ] = False,
):
    """Download an artifact from the S3 artifact bucket.

    Artifact names are always relative paths from the artifact root directory or bucket."""
    try:
        artifact_lib.download_artifact(artifact_key, force=force)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        raise typer.Exit(1)


@app.command()
def upload(
    artifact_key: Annotated[
        str,
        typer.Argument(
            help="Path to the artifact from the artifacts root or a relative path to a file/directory",
            autocompletion=_complete_local_artifacts,
        ),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Force upload even if remote files exist and would be modified. Also deletes "
            "remote files that don't exist locally.",
        ),
    ] = False,
    merge: Annotated[
        bool,
        typer.Option(
            "--merge",
            "-m",
            help="Merge the local files with the remote files. If True, will upload local files and "
            "possibly overwrite remote files, but will not delete remote files.",
        ),
    ] = False,
):
    """Upload a file or directory to the S3 artifact bucket.

    Artifact names are always relative paths from the artifact root directory or bucket.
    You can also provide a relative path to a file or directory, and the tool will determine
    the appropriate artifact key. The path must be within the artifacts directory."""
    try:
        # Load the artifact directory configuration
        data = config_lib.load_config()
        artifact_dir = pathlib.Path(data["artifact_dir"]).expanduser().resolve()

        # Check if the provided path is a relative or absolute path to a file/directory
        input_path = pathlib.Path(artifact_key)

        # If the path exists as a file or directory, resolve it
        if input_path.exists():
            # Resolve to absolute path
            abs_path = input_path.resolve()

            # Check if the path is within the artifact directory
            try:
                # Get the relative path from the artifact directory
                rel_path = abs_path.relative_to(artifact_dir)
                # Use the relative path as the artifact key
                actual_artifact_key = str(rel_path)
                print(f"Uploading {abs_path} as artifact '{actual_artifact_key}'")
            except ValueError:
                # Path is not within the artifact directory
                print(
                    f"Error: Path {abs_path} is not within the artifact directory {artifact_dir}",
                    file=sys.stderr,
                )
                raise typer.Exit(1)
        else:
            # Use the provided key as is
            actual_artifact_key = artifact_key

        # Upload the artifact using the determined key
        artifact_lib.upload_artifact(actual_artifact_key, force=force, merge=merge)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        raise typer.Exit(1)


@app.command()
def info(
    artifact_key: Annotated[
        str,
        typer.Argument(
            help="Path to the artifact from the artifacts root",
            autocompletion=_complete_both_artifacts,
        ),
    ],
):
    """Get information about an artifact.

    Artifact names are always relative paths from the artifact root directory or bucket."""
    artifact_lib.validate_artifact_path(artifact_key)

    try:
        data = config_lib.load_config()
        artifact_dir = data["artifact_dir"]
    except (KeyError, typer.Exit):
        print(
            "Error: artifact_dir not set in config. Run `luce config set-artifact-dir` first.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    local_path = pathlib.Path(artifact_dir).expanduser() / artifact_key
    local_exists = local_path.exists()
    remote_exists = artifact_lib.is_s3_object(
        artifact_lib.ARTIFACT_BUCKET, artifact_key
    ) or artifact_lib.is_s3_prefix(artifact_lib.ARTIFACT_BUCKET, artifact_key)

    if not (local_exists or remote_exists):
        print(
            f"Artifact not found (searched {local_path} and"
            f" s3://{artifact_lib.ARTIFACT_BUCKET}/{artifact_key})"
        )
        return

    # Print status
    print(f"Artifact key: {artifact_key}")

    if local_exists:
        local_info = _get_local_artifact_info(local_path)
        print(f"Local path:  {local_path} ({local_info})")

    if remote_exists:
        remote_type = (
            "File"
            if artifact_lib.is_s3_object(artifact_lib.ARTIFACT_BUCKET, artifact_key)
            else "Directory"
        )
        print(f"Remote path: s3://{artifact_lib.ARTIFACT_BUCKET}/{artifact_key} ({remote_type})")

    # If both exist, check if they're in sync
    if local_exists and remote_exists:
        cmd = artifact_lib.build_s3_download_command(
            artifact_lib.ARTIFACT_BUCKET, artifact_key, local_path, dryrun=True, delete=True
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        if not result.stdout.strip():
            print("\nLocal and remote artifacts are up to date")
        else:
            print(
                "\nLocal and remote artifacts differ; `luce artifact download` would make changes:"
            )
            print(result.stdout)


@app.command()
def rm(
    target: Annotated[
        RemoveTarget,
        typer.Argument(help="Where to remove from: local filesystem, S3, or both"),
    ],
    artifact_key: Annotated[
        str,
        typer.Argument(
            help="Path to the artifact from the artifacts root",
            autocompletion=_complete_rm_artifacts,
        ),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Remove without confirmation or existence checks",
        ),
    ] = False,
):
    """Remove an artifact from local filesystem and/or S3.

    Artifact names are always relative paths from the artifact root directory or bucket."""
    artifact_lib.validate_artifact_path(artifact_key)

    try:
        data = config_lib.load_config()
        artifact_dir = data["artifact_dir"]
    except (KeyError, typer.Exit):
        print(
            "Error: artifact_dir not set in config. Run `luce config set-artifact-dir` first.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    local_path = pathlib.Path(artifact_dir).expanduser() / artifact_key
    s3_path = f"s3://{artifact_lib.ARTIFACT_BUCKET}/{artifact_key}"

    # Check what exists
    local_exists = local_path.exists()
    remote_exists = artifact_lib.is_s3_object(
        artifact_lib.ARTIFACT_BUCKET, artifact_key
    ) or artifact_lib.is_s3_prefix(artifact_lib.ARTIFACT_BUCKET, artifact_key)

    if not force:

        # Validate targets exist
        if target in (RemoveTarget.LOCAL, RemoveTarget.BOTH) and not local_exists:
            print(f"Error: Local artifact not found at {local_path}", file=sys.stderr)
            raise typer.Exit(1)

        if target in (RemoveTarget.S3, RemoveTarget.BOTH) and not remote_exists:
            print(f"Error: Remote artifact not found at {s3_path}", file=sys.stderr)
            raise typer.Exit(1)

        # Get confirmation
        targets: list[str] = []
        if target in (RemoveTarget.LOCAL, RemoveTarget.BOTH):
            targets.append(str(local_path))
        if target in (RemoveTarget.S3, RemoveTarget.BOTH):
            targets.append(s3_path)

        print("This will remove the following paths:\n" + "\n".join(f"  {p}" for p in targets))
        response = input("Are you sure? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            return

    # Remove local
    if local_exists and target in (RemoveTarget.LOCAL, RemoveTarget.BOTH):
        if local_path.is_file():
            local_path.unlink()
        else:
            shutil.rmtree(local_path)
        print(f"Removed local artifact at {local_path}")

    # Remove remote
    if remote_exists and target in (RemoveTarget.S3, RemoveTarget.BOTH):
        subprocess.run(
            ["aws", "s3", "rm", "--recursive", s3_path],
            check=True,
        )
        print(f"Removed remote artifact at {s3_path}")


@app.command()
def check(
    prefix: Annotated[
        Optional[str],
        typer.Argument(
            help="Artifact prefix to check. If omitted, checks entire artifact directory",
            autocompletion=_complete_local_artifacts,
        ),
    ] = None,
):
    """Check if all local artifacts are synced to S3.

    Shows which artifacts need to be uploaded, if any.
    """
    try:
        data = config_lib.load_config()
        artifact_dir = data["artifact_dir"]
    except (KeyError, typer.Exit):
        print(
            "Error: artifact_dir not set in config. Run `luce config set-artifact-dir` first.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    local_path = pathlib.Path(artifact_dir).expanduser()
    if prefix:
        local_path = local_path / prefix
        s3_path = f"s3://{artifact_lib.ARTIFACT_BUCKET}/{prefix}"
    else:
        s3_path = f"s3://{artifact_lib.ARTIFACT_BUCKET}"

    # Run aws s3 sync with dry-run to see what would be uploaded
    result = subprocess.run(
        ["aws", "s3", "sync", str(local_path), s3_path, "--dryrun"],
        capture_output=True,
        text=True,
    )

    if result.stdout:
        rich.print("[yellow]These artifacts need to be uploaded:[/yellow]")
        print(result.stdout)
        rich.print(
            r"[blue]Tip:[/blue] Run [green]`luce artifact upload {file-or-directory}`[/green] "
            "to upload specific artifacts."
        )
    else:
        rich.print(f"[green]✓ All local artifacts under {local_path} are uploaded to S3[/green]")


@app.command()
def ls(
    key: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to list from the artifacts root. If omitted, lists root directory",
            autocompletion=_complete_s3_artifacts,
        ),
    ] = None,
):
    """List contents of a directory in the S3 artifact bucket.

    If no key is provided, lists the contents of the root directory.
    Shows both files and subdirectories at the specified path.
    """
    # Trim trailing slash if present
    if key and key.endswith("/"):
        key = key.rstrip("/")

    prefix = f"{key}/" if key else ""

    try:
        result = subprocess.run(
            [
                "aws",
                "s3api",
                "list-objects-v2",
                "--bucket",
                artifact_lib.ARTIFACT_BUCKET,
                "--prefix",
                prefix,
                "--delimiter",
                "/",  # Only get one level
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        response = json.loads(result.stdout)

        # Print current directory
        rich.print(f"\n[blue]Contents of s3://{artifact_lib.ARTIFACT_BUCKET}/{prefix}[/blue]\n")

        # Print directories first
        directories = [p["Prefix"] for p in response.get("CommonPrefixes", [])]
        if directories:
            rich.print("[yellow]Directories:[/yellow]")
            for dir_prefix in directories:
                # Strip the search prefix and trailing slash to get just the directory name
                dir_name = dir_prefix[len(prefix) :].rstrip("/")
                print(f"  📁 {dir_name}/")

        # Then print files
        files = [
            obj["Key"]
            for obj in response.get("Contents", [])
            if not obj["Key"].endswith("/")  # Skip directory markers
        ]
        if files:
            if directories:  # Add spacing if we printed directories
                print()
            rich.print("[yellow]Files:[/yellow]")
            for file_key in files:
                # Strip the search prefix to get just the file name
                file_name = file_key[len(prefix) :]
                if file_name:  # Only print if there's a name (excludes directory markers)
                    print(f"  📄 {file_name}")

        if not (directories or files):
            print("  (empty)")

    except subprocess.CalledProcessError as e:
        print(f"Error listing S3 contents: {e.stderr.decode()}", file=sys.stderr)
        raise typer.Exit(1)
    except json.JSONDecodeError:
        print("Error parsing S3 response", file=sys.stderr)
        raise typer.Exit(1)
