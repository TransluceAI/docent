"""
S3 cache functionality for the data registry.

Manages downloading files from S3 and caching them locally.
"""

import atexit
import gzip
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from pydantic import BaseModel, computed_field
from rich.console import Console

from .utils import log_error

console = Console()

S3_BUCKET = "docent-test-data"
S3_REGION = "us-west-1"
CACHE_DIR = Path(__file__).parent / "cache"

# Global tracking for temporary decompressed files
_temp_files: set[Path] = set()


def cleanup_temp_files():
    """Clean up all temporary decompressed files on exit."""
    for temp_path in _temp_files.copy():
        try:
            if temp_path.exists():
                temp_path.unlink()
                _temp_files.discard(temp_path)
        except Exception:
            pass  # Ignore cleanup errors


# Register cleanup function to run on exit
atexit.register(cleanup_temp_files)


class S3File(BaseModel):
    key: str  # Logical key (what users see, e.g., "thing.json")
    physical_key: str
    size: int
    last_modified: datetime | None = None

    @computed_field
    @property
    def filename(self) -> str:
        return Path(self.key).name

    @computed_field
    @property
    def size_human(self) -> str:
        size_bytes = float(self.size)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f}PB"

    @computed_field
    @property
    def is_dump_file(self) -> bool:
        return self.physical_key.endswith(".pg.tar.gz") or self.physical_key.endswith(".pg.tgz")

    def get_cache_path(self) -> Path:
        """Get cache path for the physical file (includes .gz if compressed)."""
        CACHE_DIR.mkdir(exist_ok=True)
        return CACHE_DIR / Path(self.physical_key).name

    def is_cached(self) -> bool:
        """Check if the physical file is cached locally."""
        return self.get_cache_path().exists()

    def matches_revision(self, revision: str) -> bool:
        return revision in self.key

    def __str__(self) -> str:
        return f"{self.key} ({self.size_human})"


def _get_s3_client():
    """Get S3 client with environment variable authentication."""
    try:
        return boto3.client("s3", region_name=S3_REGION)
    except NoCredentialsError:
        log_error(
            "AWS credentials not found. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables, or sign in with the AWS CLI."
        )
        raise


def _decompress_gz_file(gz_path: Path, target_filename: str) -> Path:
    """
    Decompress a .gz file to a temporary location.

    Args:
        gz_path: Path to the compressed .gz file
        target_filename: Original filename (without .gz) for the temp file

    Returns:
        Path to the temporary decompressed file
    """
    # Create temporary file with the original filename (without .gz)
    temp_dir = Path(tempfile.gettempdir()) / "docent_cache"
    temp_dir.mkdir(exist_ok=True)

    name_parts = target_filename.rsplit(".", 1)
    unique_filename = str(uuid.uuid4())
    if len(name_parts) == 2:
        temp_filename = f"{unique_filename}.{name_parts[1]}"
    else:
        temp_filename = unique_filename
    temp_path = temp_dir / temp_filename

    try:
        with gzip.open(gz_path, "rb") as gz_file:
            with open(temp_path, "wb") as temp_file:
                temp_file.write(gz_file.read())

        console.print(f"[blue]Decompressed to: {temp_path}[/blue]")

        # Track this temp file for cleanup
        _temp_files.add(temp_path)
        return temp_path

    except Exception as e:
        # Clean up temp file if decompression failed
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"Failed to decompress {gz_path}: {e}") from e


async def list_all_files() -> list[dict[str, Any]]:
    """List all files from both S3 and local cache with source indicators."""
    all_files: list[dict[str, Any]] = []

    # Get S3 files
    try:
        s3_files = await list_s3_files()
        for s3_file in s3_files:
            # Check if the physical file is cached
            is_cached = s3_file.is_cached()
            source_icons = "☁️" if not is_cached else "☁️ 💾"

            all_files.append(
                {
                    "file": s3_file,
                    "source_icons": source_icons,
                }
            )
    except Exception as e:
        console.print(f"[yellow]Warning: Could not list S3 files: {e}[/yellow]")

    # Get local-only files (files in cache that aren't on S3)
    if CACHE_DIR.exists():
        try:
            s3_filenames = {f["file"].filename for f in all_files}

            for local_file in CACHE_DIR.iterdir():
                if local_file.name.startswith("."):
                    continue
                if local_file.is_file() and local_file.name not in s3_filenames:
                    # Create a simple file object for local-only files
                    file_size = local_file.stat().st_size
                    file_modified = datetime.fromtimestamp(local_file.stat().st_mtime)

                    local_s3file = S3File(
                        key=local_file.name,
                        physical_key=local_file.name,
                        size=file_size,
                        last_modified=file_modified,
                    )

                    all_files.append(
                        {
                            "file": local_s3file,
                            "source_icons": "💾",
                        }
                    )

        except Exception as e:
            console.print(f"[yellow]Warning: Could not list local cache files: {e}[/yellow]")

    return all_files


async def list_s3_files() -> list[S3File]:
    """List all files in the S3 bucket with their metadata, normalized to logical names."""
    s3_client = _get_s3_client()

    try:
        from .utils import simple_progress

        with simple_progress("Listing S3 files...") as (progress, task):
            response = s3_client.list_objects_v2(Bucket=S3_BUCKET)

            if "Contents" not in response:
                return []

            # Collect all files and normalize .gz files to logical names
            raw_files: list[dict[str, Any]] = []
            for obj in response["Contents"]:
                raw_files.append(
                    {
                        "key": obj["Key"],
                        "size": obj["Size"],
                        "last_modified": obj.get("LastModified"),
                    }
                )

            # Normalize .gz files to logical names and handle conflicts
            normalized_files: dict[str, dict[str, Any]] = {}

            for file_data in raw_files:
                physical_key = file_data["key"]

                # Determine logical key (remove .gz if present, except for .tgz)
                if physical_key.endswith(".gz"):
                    logical_key = physical_key[:-3]  # Remove .gz
                else:
                    logical_key = physical_key

                normalized_files[logical_key] = {
                    "key": logical_key,
                    "physical_key": physical_key,
                    "size": file_data["size"],
                    "last_modified": file_data["last_modified"],
                }

            # Convert to S3File objects
            files: list[S3File] = []
            for file_data in normalized_files.values():
                files.append(S3File(**file_data))

        return files

    except ClientError as e:
        console.print(f"[red]Failed to list S3 files: {e}[/red]")
        raise


async def ensure_file_available(filename: str) -> Path:
    """
    Download a file from S3, using cache if available.

    Args:
        filename: The logical filename (what users see)
        physical_filename: The actual S3 key (may include .gz)

    Returns:
        Path to usable file (decompressed if .gz)
    """
    # Ensure cache directory exists
    CACHE_DIR.mkdir(exist_ok=True)

    # Check for regular file in cache
    regular_cache_path = CACHE_DIR / filename
    if regular_cache_path.exists():
        console.print(f"[green]Using cached file: {regular_cache_path}[/green]")
        return regular_cache_path

    # Check for .gz version in cache
    gz_cache_path = CACHE_DIR / f"{filename}.gz"
    if gz_cache_path.exists():
        console.print(f"[green]Using cached .gz file, decompressing: {gz_cache_path}[/green]")
        return _decompress_gz_file(gz_cache_path, filename)

    # Not found in cache, try to find the file in S3 listing
    s3_files = await list_s3_files()
    for s3_file in s3_files:
        if s3_file.key == filename:
            physical_filename = s3_file.physical_key
            break
    else:
        raise FileNotFoundError(f"File not found in local cache or S3: {filename}")

    s3_key = physical_filename
    cache_path = CACHE_DIR / Path(s3_key).name

    # Download from S3
    s3_client = _get_s3_client()

    try:
        from .utils import simple_progress

        with simple_progress(f"Downloading {s3_key}...") as (progress, task):
            s3_client.download_file(S3_BUCKET, s3_key, str(cache_path))

        console.print(f"[green]Downloaded and cached: {cache_path}[/green]")

        # If it's a .gz file, decompress to temp for use
        if s3_key.endswith(".gz"):
            console.print("[blue]Decompressing for use...[/blue]")
            return _decompress_gz_file(cache_path, filename)
        else:
            return cache_path

    except ClientError as e:
        console.print(f"[red]Failed to download {s3_key}: {e}[/red]")
        # Clean up partial download
        if cache_path.exists():
            cache_path.unlink()
        raise


async def upload_to_s3(local_filename: str) -> None:
    """
    Upload a file to S3.

    Args:
        local_path: Path to the local file to upload
    """
    local_path = CACHE_DIR / local_filename

    if not local_path.exists():
        raise FileNotFoundError(f"Local file not found: {local_filename}")

    s3_client = _get_s3_client()

    try:
        from .utils import simple_progress

        with simple_progress(f"Uploading {local_filename}...") as (progress, task):
            s3_client.upload_file(str(local_path), S3_BUCKET, local_filename)

        console.print(f"[green]Uploaded to S3: {local_filename}[/green]")

    except ClientError as e:
        console.print(f"[red]Failed to upload {local_filename}: {e}[/red]")
        raise


def get_cache_path_for_filename(filename: str) -> Path:
    """Get the local cache path for a filename string."""
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / filename
