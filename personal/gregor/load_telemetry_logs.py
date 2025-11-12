#!/usr/bin/env python3
"""
Script to load telemetry logs from an external database into the local database.

This script connects to an external database, retrieves telemetry logs, and imports
them into the local database. It handles ID mapping for user_id and collection_id,
updating both the database columns and any references within the json_data field. When
no collection mapping is provided the script now creates a fresh destination collection
and rewrites every collection_id to that new collection automatically. It can also
regenerate agent_run_id values so that the imported telemetry can be replayed as brand
new agent runs, and it writes the imported telemetry log IDs to a text file that can be
fed directly to replay_telemetry_logs.py.

Database configuration is read from environment variables:
    External database: EXTERNAL_PG_HOST, EXTERNAL_PG_PORT, EXTERNAL_PG_USER,
                       EXTERNAL_PG_PASSWORD, EXTERNAL_PG_DATABASE, EXTERNAL_PG_SSL
                       (EXTERNAL_PG_SSL can be 'require', 'prefer', 'allow', or 'disable', defaults to 'require')
    Local database: DOCENT_PG_HOST, DOCENT_PG_PORT, DOCENT_PG_USER,
                    DOCENT_PG_PASSWORD, DOCENT_PG_DATABASE (via MonoService)

Usage:
    python load_telemetry_logs.py --api-key dk_xxx --user-id-map old_user_id:new_user_id \\
        --collection-id-map old_collection_id:new_collection_id

    python load_telemetry_logs.py --api-key dk_xxx --collection-id collection_123 --limit 100
    python load_telemetry_logs.py --api-key dk_xxx --regenerate-agent-run-ids
    python load_telemetry_logs.py --api-key dk_xxx --log-id-output /tmp/log_ids.txt
    python load_telemetry_logs.py --api-key dk_xxx   # creates a new collection by default
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import URL, delete, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from docent._log_util import get_logger
from docent_core.docent.db.schemas.tables import SQLATelemetryLog
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.telemetry import TelemetryService

logger = get_logger(__name__)

logging.getLogger("docent_core.docent.services.telemetry").setLevel(logging.DEBUG)

# Load environment variables from .env file
load_dotenv()


def get_external_db_params() -> Dict[str, Any]:
    """Get external database connection parameters from environment variables."""
    host = os.getenv("EXTERNAL_PG_HOST", "localhost")
    port = os.getenv("EXTERNAL_PG_PORT", "15432")
    user = os.getenv("EXTERNAL_PG_USER", "docent_user")
    password = os.getenv("EXTERNAL_PG_PASSWORD", "cLphTrV2gdynYJhyLrenz7wj")
    database = os.getenv("EXTERNAL_PG_DATABASE", "docent_db")
    ssl_mode = os.getenv("EXTERNAL_PG_SSL", "require")

    if not host:
        raise ValueError("EXTERNAL_PG_HOST environment variable is required")
    if not user:
        raise ValueError("EXTERNAL_PG_USER environment variable is required")
    if not password:
        raise ValueError("EXTERNAL_PG_PASSWORD environment variable is required")
    if not database:
        raise ValueError("EXTERNAL_PG_DATABASE environment variable is required")

    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": password,
        "database": database,
        "ssl_mode": ssl_mode,
    }


def create_external_db_engine() -> AsyncEngine:
    """Create an async database engine for the external database."""
    params = get_external_db_params()

    connection_url = URL.create(
        drivername="postgresql+asyncpg",
        username=params["user"],
        password=params["password"],
        host=params["host"],
        port=params["port"],
        database=params["database"],
    )

    # Configure SSL based on ssl_mode
    ssl_mode = params["ssl_mode"].lower()
    if ssl_mode in ("require", "prefer", "allow", "disable"):
        # For asyncpg, we pass SSL via connect_args
        if ssl_mode == "disable":
            connect_args = {"ssl": False}
        elif ssl_mode == "require":
            connect_args = {"ssl": "require"}
        elif ssl_mode == "prefer":
            connect_args = {"ssl": "prefer"}
        elif ssl_mode == "allow":
            connect_args = {"ssl": "allow"}
        else:
            connect_args = {"ssl": "require"}
    else:
        # Default to require if invalid value
        connect_args = {"ssl": "require"}

    return create_async_engine(connection_url, pool_pre_ping=True, connect_args=connect_args)


def parse_id_mapping(mapping_str: str) -> Dict[str, str]:
    """Parse ID mapping from string format 'old_id:new_id'."""
    mapping = {}
    for pair in mapping_str.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise ValueError(f"Invalid mapping format: {pair}. Expected 'old_id:new_id'")
        old_id, new_id = pair.split(":", 1)
        mapping[old_id.strip()] = new_id.strip()
    return mapping


def collect_agent_run_ids(data: Any, agent_run_ids: set[str]) -> None:
    """Collect all agent_run_id values present in a nested JSON-like structure."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "agent_run_id" and isinstance(value, str):
                agent_run_ids.add(value)
            collect_agent_run_ids(value, agent_run_ids)
    elif isinstance(data, list):
        for item in data:
            collect_agent_run_ids(item, agent_run_ids)


def collect_collection_ids(data: Any, collection_ids: set[str]) -> None:
    """Collect all collection_id values present in a nested JSON-like structure."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "collection_id" and isinstance(value, str):
                collection_ids.add(value)
            collect_collection_ids(value, collection_ids)
    elif isinstance(data, list):
        for item in data:
            collect_collection_ids(item, collection_ids)


def deep_replace_ids(
    data: Any,
    user_id_map: Dict[str, str],
    collection_id_map: Dict[str, str],
    agent_run_id_map: Dict[str, str] | None = None,
) -> Any:
    """Recursively replace user_id and collection_id in JSON data structures.

    Replaces all instances of collection_id, user_id, and agent_run_id values anywhere they
    appear in the data structure, regardless of the key name. Assumes IDs are unique.
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            # Recursively process all values to replace IDs regardless of key name
            result[key] = deep_replace_ids(value, user_id_map, collection_id_map, agent_run_id_map)
        return result
    elif isinstance(data, list):
        return [
            deep_replace_ids(item, user_id_map, collection_id_map, agent_run_id_map)
            for item in data
        ]
    elif isinstance(data, str):
        # Replace all instances of collection_id and user_id, even when they appear
        # as substrings within the string
        result_str = data
        # Replace collection_ids first
        for old_id, new_id in collection_id_map.items():
            result_str = result_str.replace(old_id, new_id)
        # Then replace user_ids
        for old_id, new_id in user_id_map.items():
            result_str = result_str.replace(old_id, new_id)
        # Finally replace agent_run_ids if provided
        if agent_run_id_map:
            for old_id, new_id in agent_run_id_map.items():
                result_str = result_str.replace(old_id, new_id)
        return result_str
    else:
        return data


async def load_telemetry_logs(
    external_engine: AsyncEngine,
    api_key: str,
    user_id_map: Dict[str, str],
    collection_id_map: Dict[str, str],
    collection_id: str | None = None,
    where_clause: str | None = None,
    limit: int = 100,
    dry_run: bool = False,
    force: bool = False,
    regenerate_agent_run_ids: bool = False,
    log_id_output_path: str | None = "telemetry_log_ids.txt",
) -> None:
    """
    Load telemetry logs from external database into local database.

    Args:
        external_engine: Database engine for the external database
        api_key: API key for authentication in local database
        user_id_map: Mapping from old user_id to new user_id
        collection_id_map: Mapping from old collection_id to new collection_id
        collection_id: Optional collection ID to filter logs by
        where_clause: Optional SQL WHERE clause to filter logs (e.g., "type = 'traces'")
        limit: Maximum number of logs to load
        dry_run: If True, only show what would be imported without actually importing
        force: If True, delete existing logs before inserting new ones
        regenerate_agent_run_ids: If True, replace every agent_run_id found in json_data with a new UUID
        log_id_output_path: Destination file path for telemetry log IDs to replay later (disabled when None)
    """
    # Initialize local database service
    mono_svc = await MonoService.init()

    # Authenticate user with API key
    user = await mono_svc.get_user_by_api_key(api_key)
    if not user:
        logger.error("Invalid API key")
        sys.exit(1)

    logger.info(f"Authenticated as user: {user.email} ({user.id})")

    # Create session factory for external database
    external_session_factory = async_sessionmaker(external_engine, class_=AsyncSession)

    # Query external database for telemetry logs
    async with external_session_factory() as external_session:
        query = select(SQLATelemetryLog).order_by(SQLATelemetryLog.created_at.desc())

        if collection_id:
            # Use the original collection_id for querying the external database
            query = query.where(SQLATelemetryLog.collection_id == collection_id)

        if where_clause:
            # Apply custom WHERE clause
            query = query.where(text(where_clause))

        query = query.limit(limit)

        logger.info(f"Querying external database for telemetry logs (limit: {limit})...")
        result = await external_session.execute(query)
        external_logs = result.scalars().all()

        logger.info(f"Found {len(external_logs)} telemetry logs in external database")

        if not external_logs:
            logger.info("No telemetry logs to import")
            return

        destination_collection_id: str | None = None
        if not collection_id_map:
            timestamp_label = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
            destination_collection_name = f"Imported telemetry {timestamp_label}"
            destination_collection_description = (
                "Collection automatically created by load_telemetry_logs.py"
            )

            if dry_run:
                destination_collection_id = str(uuid4())
                logger.info(
                    "Dry run: would create new collection %s named '%s' for imported telemetry",
                    destination_collection_id,
                    destination_collection_name,
                )
            else:
                destination_collection_id = await mono_svc.create_collection(
                    user,
                    name=destination_collection_name,
                    description=destination_collection_description,
                )
                logger.info(
                    "Created collection %s named '%s' for imported telemetry logs",
                    destination_collection_id,
                    destination_collection_name,
                )

            source_collection_ids: set[str] = set()
            for external_log in external_logs:
                if external_log.collection_id:
                    source_collection_ids.add(external_log.collection_id)
                if external_log.json_data:
                    collect_collection_ids(external_log.json_data, source_collection_ids)

            if source_collection_ids:
                for old_id in source_collection_ids:
                    if destination_collection_id and old_id != destination_collection_id:
                        collection_id_map[old_id] = destination_collection_id
                logger.info(
                    "Mapped %d source collection IDs to destination collection %s",
                    len(source_collection_ids),
                    destination_collection_id,
                )
            else:
                logger.info(
                    "No collection IDs found in source logs; new collection %s will receive all data",
                    destination_collection_id,
                )
        else:
            destination_collection_id = None

        agent_run_id_map: dict[str, str] = {}
        if regenerate_agent_run_ids:
            logger.info("Regenerating agent_run_id values for all telemetry logs")
            collected_agent_run_ids: set[str] = set()
            for external_log in external_logs:
                if external_log.json_data:
                    collect_agent_run_ids(external_log.json_data, collected_agent_run_ids)
            if collected_agent_run_ids:
                agent_run_id_map = {old_id: str(uuid4()) for old_id in collected_agent_run_ids}
                logger.info(
                    f"Generated {len(agent_run_id_map)} agent_run_id replacements to avoid collisions"
                )
            else:
                logger.warning(
                    "No agent_run_id values were found in the provided telemetry logs despite "
                    "--regenerate-agent-run-ids being enabled"
                )

        # Process logs
        async with mono_svc.db.session() as local_session:
            telemetry_svc = TelemetryService(local_session, mono_svc)

            imported_count = 0
            skipped_count = 0
            error_count = 0
            replay_log_ids: list[str] = []

            for i, external_log in enumerate(external_logs, 1):
                logger.info(
                    f"Processing telemetry log {i}/{len(external_logs)}: {external_log.id} "
                    f"(type: {external_log.type})"
                )

                try:
                    # Map user_id
                    old_user_id = external_log.user_id
                    new_user_id = user_id_map.get(old_user_id, user.id)

                    if old_user_id not in user_id_map:
                        logger.warning(
                            f"User ID {old_user_id} not in mapping, using authenticated user ID {new_user_id}"
                        )

                    # Map collection_id
                    old_collection_id = external_log.collection_id
                    new_collection_id = None
                    if old_collection_id:
                        new_collection_id = collection_id_map.get(old_collection_id)
                    if not new_collection_id and destination_collection_id:
                        new_collection_id = destination_collection_id
                    if (
                        old_collection_id
                        and not new_collection_id
                        and not destination_collection_id
                    ):
                        logger.warning(
                            f"Collection ID {old_collection_id} not in mapping, setting to None"
                        )

                    log_agent_run_ids: set[str] = set()
                    if regenerate_agent_run_ids and external_log.json_data:
                        collect_agent_run_ids(external_log.json_data, log_agent_run_ids)
                        missing_agent_run_ids = [
                            old_id for old_id in log_agent_run_ids if old_id not in agent_run_id_map
                        ]
                        if missing_agent_run_ids:
                            logger.warning(
                                "No regenerated agent_run_id found for values %s in log %s",
                                missing_agent_run_ids,
                                external_log.id,
                            )

                    # Deep copy and update json_data
                    json_data = external_log.json_data.copy() if external_log.json_data else {}
                    json_data = deep_replace_ids(
                        json_data,
                        user_id_map,
                        collection_id_map,
                        agent_run_id_map if regenerate_agent_run_ids else None,
                    )

                    if dry_run:
                        logger.info(
                            f"[DRY RUN] Would import log {external_log.id}:\n"
                            f"  Old user_id: {old_user_id} -> New user_id: {new_user_id}\n"
                            f"  Old collection_id: {old_collection_id} -> New collection_id: {new_collection_id}\n"
                            f"  Type: {external_log.type}\n"
                            f"  Version: {external_log.version}\n"
                            f"  Created at: {external_log.created_at}"
                        )
                        if regenerate_agent_run_ids and log_agent_run_ids:
                            remapped_ids = {
                                old_id: agent_run_id_map.get(old_id)
                                for old_id in sorted(log_agent_run_ids)
                            }
                            logger.info("  Agent run IDs remapped: %s", remapped_ids)
                        imported_count += 1
                        replay_log_ids.append(external_log.id)
                        continue

                    # Check if log already exists in local database
                    existing_log = await telemetry_svc.get_telemetry_log(external_log.id)
                    if existing_log:
                        if force:
                            logger.info(
                                f"Telemetry log {external_log.id} already exists, deleting (--force enabled)"
                            )
                            await local_session.execute(
                                delete(SQLATelemetryLog).where(
                                    SQLATelemetryLog.id == external_log.id
                                )
                            )
                        else:
                            logger.warning(
                                f"Telemetry log {external_log.id} already exists, skipping"
                            )
                            skipped_count += 1
                            continue

                    # Insert into local database
                    local_session.add(
                        SQLATelemetryLog(
                            id=external_log.id,
                            user_id=new_user_id,
                            collection_id=new_collection_id,
                            type=external_log.type,
                            version=external_log.version,
                            json_data=json_data,
                            created_at=external_log.created_at,
                        )
                    )

                    imported_count += 1
                    replay_log_ids.append(external_log.id)

                    # Commit in batches to avoid memory issues
                    if imported_count % 50 == 0:
                        await local_session.commit()
                        logger.info(f"Committed batch of {imported_count} logs")

                except Exception as e:
                    logger.error(
                        f"Error processing telemetry log {external_log.id}: {str(e)}", exc_info=True
                    )
                    error_count += 1
                    continue

            # Final commit
            if not dry_run and imported_count > 0:
                await local_session.commit()
                logger.info("Final commit completed")

            logger.info(
                f"Import complete: {imported_count} imported, {skipped_count} skipped, {error_count} errors"
            )

            if log_id_output_path and replay_log_ids:
                if dry_run:
                    logger.info(
                        "Dry run: would write %d telemetry log IDs to %s",
                        len(replay_log_ids),
                        log_id_output_path,
                    )
                else:
                    output_path = Path(log_id_output_path).expanduser()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with output_path.open("w", encoding="utf-8") as fp:
                        for log_id in replay_log_ids:
                            fp.write(f"{log_id}\n")
                    logger.info(
                        "Wrote %d telemetry log IDs to %s for replay_telemetry_logs.py",
                        len(replay_log_ids),
                        output_path,
                    )


async def list_external_logs(
    external_engine: AsyncEngine,
    collection_id: str | None = None,
    where_clause: str | None = None,
    limit: int = 100,
) -> None:
    """List telemetry logs in the external database without importing them."""
    external_session_factory = async_sessionmaker(external_engine, class_=AsyncSession)

    async with external_session_factory() as external_session:
        query = select(SQLATelemetryLog).order_by(SQLATelemetryLog.created_at.desc())

        if collection_id:
            query = query.where(SQLATelemetryLog.collection_id == collection_id)

        if where_clause:
            # Apply custom WHERE clause
            query = query.where(text(where_clause))

        query = query.limit(limit)

        logger.info(f"Querying external database for telemetry logs (limit: {limit})...")
        result = await external_session.execute(query)
        external_logs = result.scalars().all()

        logger.info(f"Found {len(external_logs)} telemetry logs in external database")

        if not external_logs:
            logger.info("No telemetry logs found")
            return

        # Collect unique user_ids and collection_ids
        user_ids = set()
        collection_ids = set()

        for log in external_logs:
            user_ids.add(log.user_id)
            if log.collection_id:
                collection_ids.add(log.collection_id)

            # Also check json_data for collection_id
            if log.json_data:
                if isinstance(log.json_data, dict):
                    if "collection_id" in log.json_data:
                        collection_ids.add(log.json_data["collection_id"])

        logger.info("\nSummary:")
        logger.info(f"  Total logs: {len(external_logs)}")
        logger.info(f"  Unique user_ids: {len(user_ids)}")
        logger.info(f"  Unique collection_ids: {len(collection_ids)}")

        logger.info("\nUser IDs found:")
        for user_id in sorted(user_ids):
            logger.info(f"  {user_id}")

        logger.info("\nCollection IDs found:")
        for coll_id in sorted(collection_ids):
            logger.info(f"  {coll_id}")

        logger.info("\nSample logs:")
        for i, log in enumerate(external_logs[:10], 1):
            logger.info(
                f"  {i}. ID: {log.id}, Type: {log.type}, User: {log.user_id}, "
                f"Collection: {log.collection_id}, Created: {log.created_at}"
            )


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Load telemetry logs from external database into local database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Database configuration is read from environment variables:
    External database: EXTERNAL_PG_HOST, EXTERNAL_PG_PORT, EXTERNAL_PG_USER,
                       EXTERNAL_PG_PASSWORD, EXTERNAL_PG_DATABASE, EXTERNAL_PG_SSL
                       (EXTERNAL_PG_SSL can be 'require', 'prefer', 'allow', or 'disable', defaults to 'require')
    Local database: DOCENT_PG_HOST, DOCENT_PG_PORT, DOCENT_PG_USER,
                    DOCENT_PG_PASSWORD, DOCENT_PG_DATABASE

Examples:
    # List logs in external database
    python load_telemetry_logs.py --list

    # Load logs with ID mappings
    python load_telemetry_logs.py --api-key dk_xxx \\
        --user-id-map old_user_1:new_user_1,old_user_2:new_user_2 \\
        --collection-id-map old_coll_1:new_coll_1

    # Omit --collection-id-map to automatically create a fresh destination collection
    python load_telemetry_logs.py --api-key dk_xxx

    # Load logs for a specific collection
    python load_telemetry_logs.py --api-key dk_xxx --collection-id collection_123 --limit 100

    # Load logs with a WHERE clause
    python load_telemetry_logs.py --api-key dk_xxx --where "type = 'traces'"

    # Load logs with multiple filters
    python load_telemetry_logs.py --api-key dk_xxx --where "created_at > '2024-01-01'" --limit 50

    # Dry run to see what would be imported
    python load_telemetry_logs.py --api-key dk_xxx --dry-run

    # Force import (delete existing logs before inserting)
    python load_telemetry_logs.py --api-key dk_xxx --force

    # Regenerate agent run IDs to allow repeated replays as new runs
    python load_telemetry_logs.py --api-key dk_xxx --regenerate-agent-run-ids
        """,
    )

    # Local database authentication
    parser.add_argument(
        "--api-key",
        default=os.getenv("DOCENT_API_KEY"),
        help="API key for local database authentication (starts with dk_). Defaults to DOCENT_API_KEY environment variable",
    )

    # ID mapping options
    parser.add_argument(
        "--user-id-map",
        default="",
        help="Comma-separated mapping of old_user_id:new_user_id (e.g., old1:new1,old2:new2). "
        "If not provided, uses authenticated user's ID for all logs.",
    )
    parser.add_argument(
        "--collection-id-map",
        default="",
        help="Comma-separated mapping of old_collection_id:new_collection_id (e.g., old1:new1,old2:new2). "
        "If not provided, a new destination collection is created automatically and all collections map to it.",
    )
    parser.add_argument(
        "--log-id-output",
        default="log_ids.txt",
        help="File path to store imported telemetry log IDs for replay_telemetry_logs.py (set to empty string to disable)",
    )

    # Filtering options
    parser.add_argument(
        "--collection-id",
        help="Filter logs by collection ID in external database (before mapping)",
    )
    parser.add_argument(
        "--where",
        help="SQL WHERE clause to filter logs (e.g., \"type = 'traces'\" or \"created_at > '2024-01-01'\")",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of telemetry logs to load (default: 100)",
    )

    # Operation modes
    parser.add_argument(
        "--list",
        action="store_true",
        help="List telemetry logs in external database without importing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be imported without actually importing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing telemetry logs before inserting new ones if they already exist",
    )
    parser.add_argument(
        "--regenerate-agent-run-ids",
        action="store_true",
        help="Replace every agent_run_id found in json_data with a new UUID to avoid collisions when replaying logs",
    )

    args = parser.parse_args()

    # Validate API key (only needed if not listing)
    if not args.list and not args.api_key:
        logger.error(
            "API key is required. Please provide --api-key or set DOCENT_API_KEY environment variable"
        )
        sys.exit(1)

    if not args.list and not args.api_key.startswith("dk_"):
        logger.error("API key must start with 'dk_'")
        sys.exit(1)

    # Parse ID mappings
    user_id_map = parse_id_mapping(args.user_id_map) if args.user_id_map else {}
    collection_id_map = parse_id_mapping(args.collection_id_map) if args.collection_id_map else {}

    # Determine log ID output path (allow disabling via empty string)
    log_id_output_path = args.log_id_output.strip() if args.log_id_output else ""
    log_id_output_path = log_id_output_path or None

    # Create external database engine
    try:
        external_engine = create_external_db_engine()
    except Exception as e:
        logger.error(f"Failed to create external database connection: {e}")
        logger.error(
            "Please ensure EXTERNAL_PG_HOST, EXTERNAL_PG_USER, EXTERNAL_PG_PASSWORD, "
            "and EXTERNAL_PG_DATABASE environment variables are set"
        )
        sys.exit(1)

    # Run the appropriate operation with proper cleanup
    async def run_operation():
        try:
            if args.list:
                await list_external_logs(
                    external_engine, args.collection_id, args.where, args.limit
                )
            else:
                await load_telemetry_logs(
                    external_engine,
                    args.api_key,
                    user_id_map,
                    collection_id_map,
                    args.collection_id,
                    args.where,
                    args.limit,
                    args.dry_run,
                    args.force,
                    args.regenerate_agent_run_ids,
                    log_id_output_path,
                )
            logger.info("Operation completed successfully")
        finally:
            await external_engine.dispose()

    try:
        asyncio.run(run_operation())
    except KeyboardInterrupt:
        logger.info("Operation interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Operation failed: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
