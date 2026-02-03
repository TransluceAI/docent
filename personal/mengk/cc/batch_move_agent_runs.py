# pyright: ignore
# %%
# IPython autoreload setup
try:
    from IPython import get_ipython

    ipython = get_ipython()
    if ipython is not None:
        ipython.run_line_magic("load_ext", "autoreload")
        ipython.run_line_magic("autoreload", "2")
except Exception:
    pass  # Not in IPython environment

# %%
# Configuration - fill these in
import httpx

BASE_URL = "https://api.docent-bridgewater.transluce.org"  # TODO: fill in your base URL
API_KEY = "..."  # TODO: fill in your API key

# Collection IDs
SOURCE_COLLECTION_ID = "a336b411-a9bb-4355-8c62-14ebc6d7aecb"  # TODO: collection to move FROM
DESTINATION_COLLECTION_ID = "d883900b-d851-4c1f-9092-5cade5722fac"  # TODO: collection to move TO

# BASE_URL = "http://localhost:8901"  # TODO: fill in your base URL
# API_KEY = "..."  # TODO: fill in your API key

# # Collection IDs
# SOURCE_COLLECTION_ID = "2bd4b883-abba-46ad-bb8c-1f1448d51b8f"  # TODO: collection to move FROM
# DESTINATION_COLLECTION_ID = "de8e8970-0678-4da4-b969-afe585f79257"  # TODO: collection to move TO

# Batch size for pagination
BATCH_SIZE = 1000

# Dry run mode - set to False to actually perform moves
DRY_RUN = False

# DQL query to find agent runs to move (modify as needed)
DQL_QUERY_TEMPLATE = """
SELECT id, metadata_json ->> 'wandb_name'
FROM agent_runs
WHERE collection_id = '{source_collection_id}'
  AND (metadata_json ->> 'wandb_name') NOT LIKE 'eps-simplified-8q%'
  AND (metadata_json ->> 'wandb_name') NOT LIKE 'eps-simplified-4q%'
  AND (metadata_json ->> 'wandb_name') NOT LIKE 'eps-simplified-focused%'
  AND (metadata_json ->> 'wandb_name') NOT LIKE 'eps-simplified-maximal%'
LIMIT {batch_size}
"""

# DQL_QUERY_TEMPLATE = """
# SELECT id, metadata_json ->> 'wandb_name'
# FROM agent_runs
# WHERE collection_id = '{source_collection_id}'
#   AND (metadata_json ->> 'extra_field_003') = 'false'
# LIMIT {batch_size}
# """


# %%
# Helper to make authenticated requests
def get_headers():
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    return headers


# %%
# Execute a single DQL query
async def execute_dql_query(query: str) -> dict:
    """Execute a DQL query and return the response."""
    # print(query)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/rest/dql/{SOURCE_COLLECTION_ID}/execute",
            json={"dql": query},
            headers=get_headers(),
            timeout=120.0,
        )
        if response.status_code != 200:
            print(f"DQL query failed: {response.status_code}")
            print(f"Response: {response.text}")
            response.raise_for_status()
        return response.json()


# %%
# Move agent runs in batch
async def move_agent_runs_batch(client: httpx.AsyncClient, agent_run_ids: list[str]) -> dict:
    """Move multiple agent runs to the destination collection in a single request."""
    response = await client.post(
        f"{BASE_URL}/rest/{SOURCE_COLLECTION_ID}/move_agent_runs",
        json={
            "agent_run_ids": agent_run_ids,
            "destination_collection_id": DESTINATION_COLLECTION_ID,
        },
        headers=get_headers(),
        timeout=300.0,
    )
    if response.status_code != 200:
        raise Exception(f"Batch move failed: {response.status_code} - {response.text}")
    return response.json()


# %%
# Main batch move function
async def batch_move_agent_runs():
    """Orchestrate the batch move of agent runs using streaming fetch+move."""
    # Validate configuration
    if not API_KEY:
        print("ERROR: API_KEY is not set")
        return
    if not DESTINATION_COLLECTION_ID:
        print("ERROR: DESTINATION_COLLECTION_ID is not set")
        return

    print("=" * 60)
    print("Batch Move Agent Runs (Streaming)")
    print("=" * 60)
    print(f"Mode:                   {'DRY RUN' if DRY_RUN else 'LIVE'}")
    print(f"Source Collection:      {SOURCE_COLLECTION_ID}")
    print(f"Destination Collection: {DESTINATION_COLLECTION_ID}")
    print("=" * 60)
    if DRY_RUN:
        print("\n*** DRY RUN MODE - No moves will be performed ***")

    # Stream fetch + move in batches
    print("\nFetching and moving agent runs in batches...")
    total_count = 0
    total_success = 0
    total_failed = 0
    all_failed_ids: list[tuple[str, str]] = []  # (id, error_msg)
    batch_num = 0

    async with httpx.AsyncClient() as client:
        while True:
            batch_num += 1
            query = DQL_QUERY_TEMPLATE.format(
                source_collection_id=SOURCE_COLLECTION_ID, batch_size=BATCH_SIZE
            )

            print(f"\n[Batch {batch_num}] Fetching next batch...")
            result = await execute_dql_query(query)
            rows = result.get("rows", [])
            batch_count = len(rows)

            if batch_count == 0:
                print("  No more agent runs to move.")
                break

            # Extract agent run IDs (first column)
            batch_ids = [row[0] for row in rows]
            print(f"  Fetched {batch_count} agent runs, moving...")

            # Move this batch (or print IDs in dry run mode)
            if not DRY_RUN:
                batch_result = await move_agent_runs_batch(client, batch_ids)
                total_success += batch_result["succeeded_count"]
                total_failed += batch_result["failed_count"]
                for agent_run_id, error_msg in batch_result["errors"].items():
                    all_failed_ids.append((agent_run_id, error_msg))
                    print(f"  FAILED: {agent_run_id} - {error_msg}")

            total_count += batch_count
            print(f"  Batch complete: {batch_count}")

            # Check if we've processed all results
            if batch_count < BATCH_SIZE:
                print("  Last batch reached (fewer than BATCH_SIZE results)")
                break

    # Summary
    print("\n" + "=" * 60)
    print("Summary" + (" (DRY RUN)" if DRY_RUN else ""))
    print("=" * 60)
    print(f"Total:     {total_count}")
    if DRY_RUN:
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


# %%
# Run the batch move (uncomment to execute)
await batch_move_agent_runs()

# %%
