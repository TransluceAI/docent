# pyright: ignore
"""CLI script to batch move agent runs between collections."""

import argparse
import asyncio
import os
import sys
import time

import httpx

DEFAULT_OUTER_BATCH_SIZE = 10000
DEFAULT_INNER_BATCH_SIZE = 1000
# DEFAULT_DQL_QUERY_TEMPLATE = """
# SELECT id, metadata_json ->> 'wandb_name'
# FROM agent_runs
# WHERE collection_id = '{source_collection_id}'
#   AND (
#     (metadata_json ->> 'wandb_name') IS NULL
#     OR (
#       (metadata_json ->> 'wandb_name') NOT LIKE 'eps-simplified-8q%'
#       AND (metadata_json ->> 'wandb_name') NOT LIKE 'eps-simplified-4q%'
#       AND (metadata_json ->> 'wandb_name') NOT LIKE 'eps-simplified-focused%'
#       AND (metadata_json ->> 'wandb_name') NOT LIKE 'eps-simplified-maximal%'
#     )
#   )
# LIMIT {outer_batch_size}
# """
DEFAULT_DQL_QUERY_TEMPLATE = """
SELECT id, metadata_json ->> 'wandb_name'
FROM agent_runs
WHERE collection_id = '{source_collection_id}'
  AND (
    (metadata_json ->> 'wandb_name') LIKE 'eps-simplified-8q%'
    OR (metadata_json ->> 'wandb_name') LIKE 'eps-simplified-4q%'
    OR (metadata_json ->> 'wandb_name') LIKE 'eps-simplified-focused%'
    OR (metadata_json ->> 'wandb_name') LIKE 'eps-simplified-maximal%'
  )
LIMIT {outer_batch_size}
"""


def get_headers(api_key: str) -> dict[str, str]:
    """Get headers for authenticated requests."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


async def execute_dql_query(
    base_url: str,
    source_collection_id: str,
    api_key: str,
    query: str,
) -> dict:
    """Execute a DQL query and return the response."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/rest/dql/{source_collection_id}/execute",
            json={"dql": query},
            headers=get_headers(api_key),
            timeout=120.0,
        )
        if response.status_code != 200:
            print(f"DQL query failed: {response.status_code}")
            print(f"Response: {response.text}")
            response.raise_for_status()
        return response.json()


async def move_agent_runs_batch(
    client: httpx.AsyncClient,
    base_url: str,
    source_collection_id: str,
    destination_collection_id: str,
    api_key: str,
    agent_run_ids: list[str],
) -> dict:
    """Move multiple agent runs to the destination collection in a single request."""
    response = await client.post(
        f"{base_url}/rest/{source_collection_id}/move_agent_runs",
        json={
            "agent_run_ids": agent_run_ids,
            "destination_collection_id": destination_collection_id,
        },
        headers=get_headers(api_key),
        timeout=300.0,
    )
    if response.status_code != 200:
        raise Exception(f"Batch move failed: {response.status_code} - {response.text}")
    return response.json()


async def batch_move_agent_runs(
    base_url: str,
    source_collection_id: str,
    destination_collection_id: str,
    api_key: str,
    outer_batch_size: int,
    inner_batch_size: int,
    dry_run: bool,
    dql_query_template: str,
) -> None:
    """Orchestrate the batch move of agent runs using two-level batching.

    Outer batch: Fetches a large set of runs via DQL
    Inner batch: Splits outer batch into smaller chunks sent concurrently to the API
    """
    print("=" * 60)
    print("Batch Move Agent Runs (Two-Level Batching)")
    print("=" * 60)
    print(f"Mode:                   {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Source Collection:      {source_collection_id}")
    print(f"Destination Collection: {destination_collection_id}")
    print(f"Outer Batch Size:       {outer_batch_size}")
    print(f"Inner Batch Size:       {inner_batch_size}")
    print("=" * 60)
    if dry_run:
        print("\n*** DRY RUN MODE - No moves will be performed ***")

    # Stream fetch + move in batches
    print("\nFetching and moving agent runs in batches...")
    total_count = 0
    total_success = 0
    total_failed = 0
    all_failed_ids: list[tuple[str, str]] = []  # (id, error_msg)
    outer_batch_num = 0

    async with httpx.AsyncClient() as client:
        while True:
            outer_batch_num += 1
            query = dql_query_template.format(
                source_collection_id=source_collection_id,
                outer_batch_size=outer_batch_size,
            )

            print(f"\n[Outer Batch {outer_batch_num}] Fetching next batch...")
            result = await execute_dql_query(
                base_url, source_collection_id, api_key, query
            )
            rows = result.get("rows", [])
            outer_batch_count = len(rows)

            if outer_batch_count == 0:
                print("  No more agent runs to move.")
                break

            # Extract agent run IDs (first column)
            batch_ids = [row[0] for row in rows]

            # Split into inner batches
            inner_batches = [
                batch_ids[i : i + inner_batch_size]
                for i in range(0, len(batch_ids), inner_batch_size)
            ]
            print(
                f"  Fetched {outer_batch_count} agent runs, "
                f"splitting into {len(inner_batches)} inner batches..."
            )

            # Move inner batches (or print summary in dry run mode)
            if not dry_run:
                start_time = time.perf_counter()
                results = await asyncio.gather(
                    *[
                        move_agent_runs_batch(
                            client,
                            base_url,
                            source_collection_id,
                            destination_collection_id,
                            api_key,
                            batch,
                        )
                        for batch in inner_batches
                    ],
                    return_exceptions=True,
                )
                elapsed = time.perf_counter() - start_time

                # Aggregate results from all inner batches
                batch_success = 0
                batch_failed = 0
                for i, batch_result in enumerate(results):
                    if isinstance(batch_result, Exception):
                        # Count entire inner batch as failed
                        batch_failed += len(inner_batches[i])
                        print(f"  Inner batch {i + 1} FAILED: {batch_result}")
                    else:
                        batch_success += batch_result["succeeded_count"]
                        batch_failed += batch_result["failed_count"]
                        for agent_run_id, error_msg in batch_result["errors"].items():
                            all_failed_ids.append((agent_run_id, error_msg))

                total_success += batch_success
                total_failed += batch_failed
                print(
                    f"  Outer batch complete in {elapsed:.2f}s: "
                    f"{batch_success} succeeded, {batch_failed} failed"
                )

            total_count += outer_batch_count
            if dry_run:
                print(f"  Running total: {total_count} would be moved")
            else:
                print(
                    f"  Running total: {total_count} processed, "
                    f"{total_success} succeeded, {total_failed} failed"
                )

            # Check if we've processed all results
            if outer_batch_count < outer_batch_size:
                print("  Last batch reached (fewer than outer_batch_size results)")
                break

    # Summary
    print("\n" + "=" * 60)
    print("Summary" + (" (DRY RUN)" if dry_run else ""))
    print("=" * 60)
    print(f"Total:     {total_count}")
    if dry_run:
        print(f"Would move: {total_count}")
    else:
        print(f"Succeeded: {total_success}")
        print(f"Failed:    {total_failed}")
        if all_failed_ids:
            print("\nFailed agent run IDs:")
            for agent_run_id, error_msg in all_failed_ids[:10]:  # Show first 10
                print(f"  {agent_run_id}: {error_msg[:80]}")
            if len(all_failed_ids) > 10:
                print(f"  ... and {len(all_failed_ids) - 10} more")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch move agent runs between collections.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
  DOCENT_API_KEY    API key for authentication (required)

Examples:
  # Dry run (default) to see what would be moved
  python batch_move_agent_runs.py --base-url https://api.example.com \\
    --source-collection-id abc123 --destination-collection-id def456

  # Actually perform the move
  python batch_move_agent_runs.py --base-url https://api.example.com \\
    --source-collection-id abc123 --destination-collection-id def456 --no-dry-run
""",
    )

    parser.add_argument(
        "--base-url",
        required=True,
        help="API base URL (e.g., https://api.docent-bridgewater.transluce.org)",
    )
    parser.add_argument(
        "--source-collection-id",
        required=True,
        help="Collection ID to move agent runs FROM",
    )
    parser.add_argument(
        "--destination-collection-id",
        required=True,
        help="Collection ID to move agent runs TO",
    )
    parser.add_argument(
        "--outer-batch-size",
        type=int,
        default=DEFAULT_OUTER_BATCH_SIZE,
        help=f"Number of agent runs to fetch per DQL query (default: {DEFAULT_OUTER_BATCH_SIZE})",
    )
    parser.add_argument(
        "--inner-batch-size",
        type=int,
        default=DEFAULT_INNER_BATCH_SIZE,
        help=f"Number of agent runs per API move request (default: {DEFAULT_INNER_BATCH_SIZE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        dest="dry_run",
        help="Run in dry-run mode without performing moves (default)",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_false",
        dest="dry_run",
        help="Actually perform the moves",
    )
    parser.add_argument(
        "--dql-query",
        default=DEFAULT_DQL_QUERY_TEMPLATE,
        help="Custom DQL query template (must include {source_collection_id} and {outer_batch_size} placeholders)",
    )

    args = parser.parse_args()

    # Read API key from environment
    api_key = os.environ.get("DOCENT_API_KEY")
    if not api_key:
        print("ERROR: DOCENT_API_KEY environment variable is not set", file=sys.stderr)
        sys.exit(1)

    asyncio.run(
        batch_move_agent_runs(
            base_url=args.base_url,
            source_collection_id=args.source_collection_id,
            destination_collection_id=args.destination_collection_id,
            api_key=api_key,
            outer_batch_size=args.outer_batch_size,
            inner_batch_size=args.inner_batch_size,
            dry_run=args.dry_run,
            dql_query_template=args.dql_query,
        )
    )


if __name__ == "__main__":
    main()
