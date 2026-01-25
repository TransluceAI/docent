# autoflake: skip_file
# pyright: ignore

# %%

# import IPython

# IPython.get_ipython().run_line_magic("load_ext", "autoreload")  # type: ignore
# IPython.get_ipython().run_line_magic("autoreload", "2")  # type: ignore

# %%

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic_core import to_jsonable_python
from tqdm import tqdm

from docent import Docent
from docent_core._env_util import ENV

DOCENT_API_KEY = ENV.get("DOCENT_API_KEY")
DOCENT_DOMAIN = ENV.get("DOCENT_DOMAIN")
if not DOCENT_DOMAIN or not DOCENT_API_KEY:
    raise ValueError("DOCENT_API_KEY and DOCENT_DOMAIN must be set")
dc = Docent(api_key=DOCENT_API_KEY, domain=DOCENT_DOMAIN)

# %%

COLLECTION_ID = "07287acb-8908-4f4c-95ec-8cdeadcb4423"

# Get all agent run IDs
agent_run_ids = dc.list_agent_run_ids(COLLECTION_ID)
print(f"Found {len(agent_run_ids)} agent runs")

# %%

# Download all agent runs
MAX_WORKERS = 50


def download_single_run(agent_run_id: str):
    return dc.get_agent_run(COLLECTION_ID, agent_run_id)


agent_runs = []
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    future_to_id = {
        executor.submit(download_single_run, run_id): run_id
        for run_id in agent_run_ids
    }

    for future in tqdm(
        as_completed(future_to_id), total=len(agent_run_ids), desc="Downloading agent runs"
    ):
        agent_run = future.result()
        if agent_run is not None:
            agent_runs.append(to_jsonable_python(agent_run))

print(f"Downloaded {len(agent_runs)} agent runs")

# %%

# Save to JSON file
output_file = f"agent_runs_{COLLECTION_ID}.json"
with open(output_file, "w") as f:
    json.dump(agent_runs, f, indent=2)

print(f"Saved to {output_file}")

# %%
