"""
Restore functionality using dump files.

Restores dump files, handling collection ownership and alembic revision compatibility.
"""

import os
import subprocess
from pathlib import Path
from typing import Any, Sequence

from .cache import ensure_file_available
from .constants import CSV_TABLES
from .db_utils import get_db_connection_params, get_default_user_id
from .utils import (
    count_csv_rows,
    log_error,
    log_info,
    log_success,
    log_warning,
)


async def restore_file(filename: str) -> None:
    """Restore a collection export file (.pg.tgz format)."""
    local_path = await ensure_file_available(filename)
    log_info(f"Restoring from: {local_path}")

    import json
    import tarfile
    import tempfile

    collection_id = None
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Extract and read metadata
        with tarfile.open(local_path, "r:gz") as tar:
            tar.extractall(temp_path)

        metadata_files = list(temp_path.glob("*_metadata.json"))
        if metadata_files:
            with open(metadata_files[0], "r") as f:
                metadata = json.load(f)
                collection_id = metadata.get("collection_id")
                log_info(
                    f"Restoring: {metadata.get('collection_name', 'Unknown')} ({collection_id})"
                )

        # Prepare CSV files for restore
        csv_files_to_restore: list[tuple[str, Path, int]] = []
        for table_name in CSV_TABLES:
            csv_files = list(temp_path.glob(f"*{table_name}.csv"))
            if not csv_files or count_csv_rows(csv_files[0]) == 0:
                continue

            csv_file = csv_files[0]
            # Update created_at and ownership for collections
            if table_name == "collections":
                csv_file = await _update_collections_timestamps(csv_file, temp_path)
            # Update user_id for access_control_entries
            elif table_name == "access_control_entries":
                csv_file = await _update_access_control_entries(csv_file, temp_path)

            csv_files_to_restore.append((table_name, csv_file, count_csv_rows(str(csv_file))))

        if not csv_files_to_restore:
            log_warning("No valid CSV files found")
            return

        # Restore in transaction
        db_params = get_db_connection_params()

        await _restore_csv_files(db_params, csv_files_to_restore)

        # Report results
        for table_name, _, row_count in csv_files_to_restore:
            if table_name == "collections":
                suffix = " (updated created_at, reassigned ownership)"
            elif table_name == "access_control_entries":
                suffix = " (reassigned user_id)"
            else:
                suffix = ""
            log_success(f"✓ {table_name}: {row_count} rows{suffix}")


async def _update_collections_timestamps(csv_file: Path, temp_path: Path) -> Path:
    """Update created_at timestamps and ownership in collections CSV."""
    import csv
    from datetime import UTC, datetime

    # Get the default user ID for ownership reassignment
    try:
        default_user_id = await get_default_user_id()
        log_info(f"Reassigning collection ownership to default user: {default_user_id}")
    except ValueError as e:
        log_error(f"Failed to get default user: {e}")
        log_error("Collections cannot be restored without a valid owner")
        raise ValueError(f"Default user not found: {e}") from e

    updated_path = temp_path / f"updated_{csv_file.name}"
    with open(csv_file, "r") as infile, open(updated_path, "w", newline="") as outfile:
        reader = csv.DictReader(infile)
        if not reader.fieldnames:
            return csv_file

        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
        writer.writeheader()

        for row in reader:
            # Log the collection being processed
            if "id" in row:
                log_info(f"Processing collection: {row['id']} - {row.get('name', 'Unknown')}")

            # Update timestamps
            if "created_at" in row:
                row["created_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()

            # Reassign ownership to default user
            if "created_by" in row:
                original_owner = row["created_by"]
                row["created_by"] = default_user_id
                if original_owner != default_user_id:
                    log_info(f"Changed owner from {original_owner} to {default_user_id}")

            writer.writerow(row)

    return updated_path


async def _update_access_control_entries(csv_file: Path, temp_path: Path) -> Path:
    """Update user_id in access_control_entries CSV to default user."""
    import csv

    # Get the default user ID for user reassignment
    try:
        default_user_id = await get_default_user_id()
        log_info(f"Reassigning ACL user_id to default user: {default_user_id}")
    except ValueError as e:
        log_error(f"Failed to get default user: {e}")
        raise ValueError(f"Default user not found: {e}") from e

    updated_path = temp_path / f"updated_{csv_file.name}"
    with open(csv_file, "r") as infile, open(updated_path, "w", newline="") as outfile:
        reader = csv.DictReader(infile)
        if not reader.fieldnames:
            return csv_file

        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
        writer.writeheader()

        for row in reader:
            # Reassign user_id to default user
            if "user_id" in row:
                original_user = row["user_id"]
                row["user_id"] = default_user_id
                if original_user != default_user_id:
                    log_info(f"Changed ACL user_id from {original_user} to {default_user_id}")

            writer.writerow(row)

    return updated_path


async def _restore_csv_files(
    db_params: dict[str, Any],
    csv_files_to_restore: Sequence[tuple[str, Path, int]],
) -> None:
    """Execute all CSV restore operations in a single database transaction."""
    # Create a single SQL script with all COPY commands in a transaction
    sql_script_content = ["BEGIN;"]

    for table_name, csv_file_path, _ in csv_files_to_restore:
        # Use absolute path to avoid issues with psql working directory
        abs_csv_path = csv_file_path.resolve()
        copy_command = f"\\copy {table_name} FROM '{abs_csv_path}' WITH CSV HEADER;"
        sql_script_content.append(copy_command)

    sql_script_content.append("COMMIT;")

    log_info("Executing restore transaction...")

    # Execute the transaction script directly via stdin
    psql_cmd = [
        "psql",
        f"--host={db_params['host']}",
        f"--port={db_params['port']}",
        f"--username={db_params['user']}",
        f"--dbname={db_params['database']}",
        "--echo-errors",
    ]

    try:
        env = os.environ.copy()
        env["PGPASSWORD"] = db_params["password"]

        log_info("Executing SQL transaction...")
        log_info(f"SQL commands: {len(sql_script_content)} statements")

        result = subprocess.run(
            psql_cmd,
            input="\n".join(sql_script_content),
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )

        # Log any output from psql (warnings, notices, etc.)
        if result.stdout.strip():
            log_info(f"PostgreSQL output: {result.stdout.strip()}")
        if result.stderr.strip():
            log_warning(f"PostgreSQL messages: {result.stderr.strip()}")

    except subprocess.CalledProcessError as e:
        log_error("Restore transaction failed - all changes rolled back")
        log_error(f"Exit code: {e.returncode}")
        if e.stdout:
            log_error(f"stdout: {e.stdout}")
        if e.stderr:
            log_error(f"stderr: {e.stderr}")
        log_error("SQL script that failed:")
        for i, line in enumerate(sql_script_content, 1):
            log_error(f"  {i}: {line}")
        raise ValueError(f"Database restore failed: {e.stderr or e.stdout}") from e
