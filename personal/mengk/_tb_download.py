# %%

"""Optimized script to download agent runs with concurrent requests and batching."""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import dotenv
from tqdm import tqdm

from docent import Docent

dotenv.load_dotenv()

# Configuration
# collection_id = "c35d21f8-754e-4b9b-9c0d-9b5a97130b41"
collection_id = "27960064-f625-433a-ac20-5d394b974000"
# output_file = "termbench-gpt5-1.json"
output_file = "termbench-gpt5_gitignore.json"
checkpoint_file = "termbench-gpt5-checkpoint_gitignore.json"
max_workers = 10  # Number of concurrent requests
checkpoint_interval = 50  # Save checkpoint every N runs


def load_checkpoint():
    """Load previously downloaded runs if checkpoint exists."""
    if Path(checkpoint_file).exists():
        with open(checkpoint_file, "r") as f:
            data = json.load(f)
            return data.get("agent_runs", []), set(data.get("completed_ids", []))
    return [], set()


def save_checkpoint(agent_runs, completed_ids):
    """Save current progress to checkpoint file."""
    with open(checkpoint_file, "w") as f:
        json.dump(
            {
                "agent_runs": [run.model_dump(mode="json") for run in agent_runs],
                "completed_ids": list(completed_ids),
            },
            f,
        )


def download_agent_run(client, collection_id, run_id):
    """Download a single agent run with retry logic."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return client.get_agent_run(collection_id, run_id)
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"\nFailed to download {run_id} after {max_retries} attempts: {e}")
                return None
            time.sleep(1)  # Wait before retry


def main():
    client = Docent()

    # Load checkpoint if exists
    agent_runs, completed_ids = load_checkpoint()
    print(f"Loaded checkpoint: {len(completed_ids)} runs already downloaded")

    # Get all run IDs
    all_run_ids = client.list_agent_run_ids(collection_id)
    remaining_ids = [rid for rid in all_run_ids if rid not in completed_ids]

    print(f"Total runs: {len(all_run_ids)}")
    print(f"Remaining to download: {len(remaining_ids)}")

    if not remaining_ids:
        print("All runs already downloaded!")
    else:
        # Download runs concurrently
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_id = {
                executor.submit(download_agent_run, client, collection_id, run_id): run_id
                for run_id in remaining_ids
            }

            # Process completed downloads
            with tqdm(total=len(remaining_ids), desc="Downloading agent runs") as pbar:
                for i, future in enumerate(as_completed(future_to_id)):
                    run_id = future_to_id[future]
                    result = future.result()

                    if result is not None:
                        agent_runs.append(result)
                        completed_ids.add(run_id)

                    pbar.update(1)

                    # Save checkpoint periodically
                    if (i + 1) % checkpoint_interval == 0:
                        save_checkpoint(agent_runs, completed_ids)
                        pbar.write(f"Checkpoint saved ({len(completed_ids)} runs)")

    # Final save
    print(f"\nDownload complete! Total runs: {len(agent_runs)}")

    # Save final results
    with open(output_file, "w") as f:
        json.dump([run.model_dump(mode="json") for run in agent_runs], f)
    print(f"Saved to {output_file}")

    # Optionally upload to docent (uncomment if needed)
    # print("Uploading to docent...")
    # client.add_agent_runs(collection_id, agent_runs)
    # print("Upload complete!")

    # Clean up checkpoint file
    if Path(checkpoint_file).exists():
        Path(checkpoint_file).unlink()
        print("Checkpoint file removed")


# %%

main()
# %%
