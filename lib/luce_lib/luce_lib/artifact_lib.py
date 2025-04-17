"""Utilities for working with artifacts."""

import dataclasses
import datetime
import pathlib
import subprocess
from logging import getLogger
from typing import Callable, Literal

import boto3
from botocore.exceptions import ClientError
from luce_lib import config_lib

logger = getLogger(__name__)

ARTIFACT_BUCKET = "transluce-artifacts-private"
INVALID_PATH_CHARS = {"*", "?", "[", "]", "!"}


@dataclasses.dataclass
class LazyFormatVariable:
    fn: Callable[[], str]

    def __str__(self) -> str:
        return self.fn()


def get_artifact_path(
    key: str,
    *,
    format: bool = False,
    download: bool | Literal["force"] = False,
    ensure_empty: bool = False,
    format_extra: dict[str, str] = {},
) -> pathlib.Path:
    """Get the path to an artifact, downloading it if necessary.

    The key can optionally be formatted using the substitution variables below (if format=True):

    - {user}: The current user name, taken from the key "name" in ~/.luce/config.toml or inferred
        from the OS username.
    - {date}: The current date in the format YYYY-MM-DD.
    - {timestamp}: The current timestamp in the format YYYY-MM-DD-HH-MM-SS.

    Args:
        key: The key of the artifact to get. Should be relative to the artifact directory.
        format: Whether to format the key string using the substitution variables above.
        download: Whether to download the artifact. If True, the artifact will be downloaded from
            AWS before returning the path. If "force", the artifact will be downloaded even if
            local files exist and would be modified.
        ensure_empty: Whether to ensure the artifact path is empty. If True, will raise an error
            if the artifact path is not empty either locally or remotely. Useful when you want to
            ensure that you're not going to conflict with an existing artifact.
        format_extra: Extra variables to pass to the format function.

    Returns:
        The path to the artifact as an absolute path.
    """
    if download and ensure_empty:
        raise ValueError("Cannot ensure_empty and download at the same time")

    if format_extra and not format:
        raise ValueError("Cannot use format_extra without format=True")

    if format:
        format_dict: dict[str, LazyFormatVariable | str] = {
            "user": LazyFormatVariable(config_lib.get_user_name),
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S"),
        }
        format_dict.update(format_extra)
        key = key.format(**format_dict)

    result = config_lib.get_artifact_dir() / key

    if download:
        download_artifact(key, force=(download == "force"))

    if ensure_empty:
        if result.exists():
            raise RuntimeError(f"Error: Artifact path is not empty locally: {result}")

        if is_s3_object_or_prefix(ARTIFACT_BUCKET, key):
            raise RuntimeError(f"Error: Artifact path is not empty on S3: {key}")

    return result


def validate_artifact_path(artifact_key: str) -> None:
    """Validate an artifact path doesn't contain special characters.

    Invalid characters are: {"*", "?", "[", "]", "!"}. These are invalid because they are used as
    wildcards in the aws s3 sync command.

    Args:
        artifact_key: Path to the artifact from the artifacts root

    Raises:
        RuntimeError: If path contains invalid characters
    """
    invalid_chars = set(artifact_key) & INVALID_PATH_CHARS
    if invalid_chars:
        raise RuntimeError(
            "Error: Artifact path contains unsupported characters: "
            f"{', '.join(sorted(invalid_chars))}"
        )


def is_s3_object(bucket: str, key: str) -> bool:
    """Check if an S3 path points to an object (file) rather than prefix (directory).

    Args:
        bucket: S3 bucket name
        key: Object key (path within bucket)

    Returns:
        True if path points to an object, False if it's a prefix or doesn't exist
    """
    try:
        s3_client = boto3.client("s3")
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        # Check specifically for 404 Not Found
        if e.response["Error"]["Code"] == "404":
            return False
        # Re-raise other errors
        raise


def is_s3_prefix(bucket: str, key: str) -> bool:
    """Check if an S3 path exists as a nonempty prefix (directory).

    Args:
        bucket: S3 bucket name
        key: Object key (path within bucket)

    Returns:
        True if path exists as a nonempty prefix
    """
    # Ensure key ends with / for directory-style prefix matching
    if not key.endswith("/"):
        key = f"{key}/"

    s3_client = boto3.client("s3")
    response = s3_client.list_objects_v2(
        Bucket=bucket, Prefix=key, MaxKeys=1  # We only need to know if there's at least one
    )
    return bool(response.get("Contents"))


def is_s3_object_or_prefix(bucket: str, key: str) -> bool:
    """Check if an S3 path exists as an object or prefix."""
    return is_s3_object(bucket, key) or is_s3_prefix(bucket, key)


def build_s3_download_command(
    bucket: str,
    key: str,
    local_path: pathlib.Path,
    *,
    dryrun: bool = False,
    delete: bool = False,
) -> list[str]:
    """Build aws s3 sync command to download from S3 to local.

    Args:
        bucket: S3 bucket name
        key: Object key (path within bucket)
        local_path: Local path to sync to
        dryrun: If True, add --dryrun flag
        delete: If True, add --delete flag

    Returns:
        Command as list of strings
    """
    cmd = ["aws", "s3", "sync"]
    if dryrun:
        cmd.append("--dryrun")
    if delete:
        cmd.append("--delete")

    s3_path = f"s3://{bucket}/{key}"
    if is_s3_object(bucket, key):
        # For files, sync the parent directory but include only this file
        s3_parent = f"s3://{bucket}/{pathlib.Path(key).parent}"
        local_parent = local_path.parent
        file_name = local_path.name
        cmd.extend(
            [
                # Order matters: exclude everything first, then include our file
                "--exclude",
                "*",
                "--include",
                file_name,
                s3_parent,
                str(local_parent),
            ]
        )
    else:
        # For directories, sync normally
        cmd.extend([s3_path, str(local_path)])

    return cmd


def build_s3_upload_command(
    bucket: str,
    key: str,
    local_path: pathlib.Path,
    *,
    dryrun: bool = False,
    delete: bool = False,
) -> list[str]:
    """Build aws s3 sync command to upload to S3 from local.

    Args:
        bucket: S3 bucket name
        key: Object key (path within bucket)
        local_path: Local path to sync from
        dryrun: If True, add --dryrun flag
        delete: If True, add --delete flag

    Returns:
        Command as list of strings
    """
    cmd = ["aws", "s3", "sync"]
    if dryrun:
        cmd.append("--dryrun")
    if delete:
        cmd.append("--delete")

    s3_path = f"s3://{bucket}/{key}"
    if local_path.is_file():
        # For files, sync the parent directory but include only this file
        s3_parent = f"s3://{bucket}/{pathlib.Path(key).parent}"
        local_parent = local_path.parent
        file_name = local_path.name
        cmd.extend(
            [
                # Order matters: exclude everything first, then include our file
                "--exclude",
                "*",
                "--include",
                file_name,
                str(local_parent),
                s3_parent,
            ]
        )
    else:
        # For directories, sync normally
        cmd.extend([str(local_path), s3_path])

    return cmd


def download_artifact(
    artifact_key: str,
    force: bool = False,
    allow_empty: bool = False,
):
    """Download an artifact from the S3 artifact bucket.

    Artifact names are always relative paths from the artifact root directory or bucket.

    Args:
        artifact_key: The key of the artifact to download. Should be relative to the artifact directory.
        force: Whether to force download even if local files exist and would be modified.
        allow_empty: Whether to allow the artifact path to be empty. If True, will not raise an
            error if the artifact path is missing remotely.
    """
    validate_artifact_path(artifact_key)

    try:
        data = config_lib.load_config()
        artifact_dir = data["artifact_dir"]
    except KeyError:
        raise RuntimeError(
            "Error: artifact_dir not set in config. Run `luce config set-artifact-dir` first.",
        )

    local_path = pathlib.Path(artifact_dir).expanduser() / artifact_key

    if (not allow_empty) and (not is_s3_object_or_prefix(ARTIFACT_BUCKET, artifact_key)):
        raise RuntimeError(f"Error: Artifact path does not exist on S3: {artifact_key}")

    # Check if path exists and we're not in force mode
    if local_path.exists() and not force:
        # Do a dry run to check for changes
        cmd = build_s3_download_command(
            ARTIFACT_BUCKET, artifact_key, local_path, dryrun=True, delete=True
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        if not result.stdout.strip():
            logger.info(f"Artifact '{artifact_key}' is already up to date")
            return

        raise RuntimeError(
            f"Error: Local files exist at {local_path} and would be modified by download.\n"
            f"Changes that would be made:\n{result.stdout}\n"
            "Run with --force (or `force=True` from scripts) to overwrite local files."
        )
    else:

        # Either path doesn't exist or we're in force mode
        cmd = build_s3_download_command(ARTIFACT_BUCKET, artifact_key, local_path, delete=force)

        logger.info(f"Downloading artifact '{artifact_key}' from S3...")
        result = subprocess.run(cmd, check=True)
        logger.info(f"Successfully downloaded artifact '{artifact_key}'")


def upload_artifact(
    artifact_key: str,
    force: bool = False,
    allow_empty: bool = False,
    merge: bool = False,
):
    """Upload an artifact to the S3 artifact bucket.

    Artifact names are always relative paths from the artifact root directory or bucket.

    Args:
        artifact_key: The key of the artifact to upload. Should be relative to the artifact directory.
        force: Whether to force upload even if remote files exist and would be modified. Also
            deletes remote files that don't exist locally.
        allow_empty: Whether to allow the artifact path to be empty. If True, will not raise an
            error if the artifact path is missing locally.
        merge: Whether to merge the local files with the remote files. If True, will upload local
            files and possibly overwrite remote files, but will not delete remote files.
    """
    if force and merge:
        raise ValueError("Cannot force and merge at the same time")

    validate_artifact_path(artifact_key)

    try:
        data = config_lib.load_config()
        artifact_dir = data["artifact_dir"]
    except KeyError:
        raise RuntimeError(
            "Error: artifact_dir not set in config. Run `luce config set-artifact-dir` first.",
        )

    local_path = pathlib.Path(artifact_dir).expanduser() / artifact_key

    if (not local_path.exists()) and (not allow_empty):
        raise RuntimeError(f"Error: Local path does not exist: {local_path}")

    if merge:
        # Run in merge mode
        cmd = build_s3_upload_command(ARTIFACT_BUCKET, artifact_key, local_path, delete=False)

        logger.info(f"Uploading artifact '{artifact_key}' to S3...")
        result = subprocess.run(cmd, check=True)
        logger.info(f"Successfully uploaded artifact '{artifact_key}'")
    elif (
        is_s3_object(ARTIFACT_BUCKET, artifact_key) or is_s3_prefix(ARTIFACT_BUCKET, artifact_key)
    ) and not force:
        # File exists and not in force or merge mode; do a dry run to check for changes
        cmd = build_s3_upload_command(
            ARTIFACT_BUCKET, artifact_key, local_path, dryrun=True, delete=True
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        if not result.stdout.strip():
            logger.info(f"Artifact '{artifact_key}' is already up to date")
            return

        raise RuntimeError(
            f"Error: Remote files exist at s3://{ARTIFACT_BUCKET}/{artifact_key} "
            "and would be modified by upload.\n"
            f"Changes that would be made:\n{result.stdout}\n"
            "Run with --force (or `force=True` from scripts) to overwrite or delete mismatched "
            "remote files. Run with --merge (or `merge=True` from scripts) to upload local files "
            "and possibly overwrite remote files when modified locally (without deleting remote "
            "files otherwise)."
        )
    else:

        # Either remote path doesn't exist or we're in force mode
        cmd = build_s3_upload_command(ARTIFACT_BUCKET, artifact_key, local_path, delete=force)

        logger.info(f"Uploading artifact '{artifact_key}' to S3...")
        result = subprocess.run(cmd, check=True)

        logger.info(f"Successfully uploaded artifact '{artifact_key}'")
