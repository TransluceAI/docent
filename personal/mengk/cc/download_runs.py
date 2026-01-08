# autoflake: skip_file
# pyright: ignore

# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")  # type: ignore
IPython.get_ipython().run_line_magic("autoreload", "2")  # type: ignore

# %%

import json

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

COLLECTION_ID = "a641fb57-351f-4681-8510-984789fb5124"

# Get all agent run IDs
agent_run_ids = dc.list_agent_run_ids(COLLECTION_ID)
print(f"Found {len(agent_run_ids)} agent runs")

# %%

# Download all agent runs
agent_runs = []
for agent_run_id in tqdm(agent_run_ids, desc="Downloading agent runs"):
    agent_run = dc.get_agent_run(COLLECTION_ID, agent_run_id)
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
