"""
Data registry CLI for Docent.

This provides utilities for ingesting and restoring data for testing purposes.
Supports ingesting data via the Docent SDK and restoring from database dump files.
"""

import asyncio
import sys

import typer
from rich.console import Console
from rich.prompt import Confirm

from data.ingest import TEST_USER_EMAIL

app = typer.Typer(help="Data registry for Docent testing data")
console = Console()

# Import all modules at the top level to avoid relative import issues
from . import cache
from .constants import DB_RESTORE_EXTENSION
from .db_utils import get_current_alembic_revision
from .dump import dump_collection, select_collection_from_menu
from .ingest import ingest_file
from .restore import restore_file
from .utils import create_aligned_file_display, log_error, log_info, log_success, log_warning


@app.command()
def ingest(filename: str = typer.Argument(None, help="File to ingest")):
    """Ingest data using the Docent Python SDK."""
    asyncio.run(_ingest_async(filename))


@app.command()
def restore(filename: str = typer.Argument(None, help="Dump file to restore")):
    """Restore data from a dump file."""
    asyncio.run(_restore_async(filename))


@app.command()
def dump(
    collection_id: str = typer.Argument(None, help="Collection ID to dump"),
    name: str = typer.Option(None, help="Custom name for the dump"),
):
    """Create a dump file for a collection."""
    asyncio.run(_dump_async(collection_id, name))


async def _ingest_async(filename: str | None):
    """Async implementation of ingest command."""

    if not filename:
        filename = await _select_file_from_s3(for_ingest=True)
        if not filename:
            log_error("No file selected")
            return

    try:
        await ingest_file(filename)
    except Exception:
        sys.exit(1)


async def _restore_async(filename: str | None):
    """Async implementation of restore command."""

    if not filename:
        filename = await _select_file_from_s3(for_ingest=False)
        if not filename:
            log_error("No file selected")
            return
    else:
        # Try to find a matching file with current alembic revision
        resolved_filename = await _resolve_restore_filename(filename)
        if resolved_filename:
            filename = resolved_filename
        # If not resolved, still try the original filename - restore_file will handle it

    await restore_file(filename)
    log_success(f"Restored {filename} to user {TEST_USER_EMAIL}")


async def _resolve_restore_filename(base_filename: str) -> str | None:
    """
    Resolve a base filename to a full filename with alembic revision.

    This function tries to find the most appropriate filename for the current
    schema revision. If a suitable filename is found, it's returned; otherwise,
    None is returned and the caller should try the original filename.

    Args:
        base_filename: Base filename like 'sonnet_36_pico_original'

    Returns:
        Full filename if a revision-specific match is found, or None
    """
    current_revision = await get_current_alembic_revision()

    # If it's already a full filename with extension, return as-is
    if base_filename.endswith(DB_RESTORE_EXTENSION):
        return base_filename

    # Try with current revision
    full_filename = f"{base_filename}.{current_revision}.{DB_RESTORE_EXTENSION}"

    # Check if this revision-specific file exists in cache
    cache_path = cache.get_cache_path_for_filename(full_filename)
    if cache_path.exists():
        log_success(f"Found revision-specific file in cache: {full_filename}")
        return full_filename

    # Check if it exists on S3 by trying to list files
    try:
        all_files = await cache.list_s3_files()
        for s3_file in all_files:
            if s3_file.key == full_filename:
                log_info(f"Found revision-specific file on S3: {full_filename}")
                return full_filename
    except Exception:
        pass  # S3 listing failed, continue

    log_info(
        f"No revision-specific file found for '{base_filename}' with revision {current_revision}"
    )
    return None


async def _dump_async(collection_id: str | None, name: str | None):
    """Async implementation of dump command."""

    if not collection_id:
        collection_id = await select_collection_from_menu()
        if not collection_id:
            log_error("No collection selected")
            return

    try:
        dump_filename = await dump_collection(collection_id, name)
        log_success(f"Successfully created dump: {dump_filename}")

        if Confirm.ask("Upload to S3 bucket?"):
            await cache.upload_to_s3(dump_filename)
    except Exception:
        sys.exit(1)


async def _select_file_from_s3(for_ingest: bool) -> str | None:
    """Show a menu to select a file from S3 and local cache."""
    import beaupy

    try:
        all_files = await cache.list_all_files()

        if for_ingest:
            # Filter out .dump files for ingest
            filtered_files = [f for f in all_files if not f["file"].is_dump_file]
        else:
            # Only show dump/export files for restore (.pg.tgz)
            current_revision = await get_current_alembic_revision()
            console.print(f"Current schema revision: {current_revision}")
            filtered_files = [f for f in all_files if f["file"].is_dump_file]

            # Prefer files with matching revision
            filtered_files = [
                f for f in filtered_files if f["file"].matches_revision(current_revision)
            ]

        if not filtered_files:
            log_warning("No suitable files found")
            return None

        # Create aligned display options
        display_options, file_keys = create_aligned_file_display(filtered_files)

        log_info("Select a file:")
        selected_display = beaupy.select(display_options)
        if selected_display is None:
            return None

        # beaupy.select returns the selected item, find the corresponding key
        for i, display_option in enumerate(display_options):
            if display_option == selected_display:
                return file_keys[i]

        return None
    except Exception as e:
        log_error("Failed to list files", e)
        return None


if __name__ == "__main__":
    app()
