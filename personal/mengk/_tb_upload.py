# %%

"""Optimized script to download agent runs with concurrent requests and batching."""

import json

from docent import Docent
from docent.data_models import AgentRun

# Configuration
collection_id = "7d99d911-8bfd-44f1-bb06-ca4ad59c5c3e"
input_files = [
    "_termbench-gpt51_gitignore.json",
]

client = Docent(server_url="http://localhost:8890")

for input_file in input_files:
    print(f"Processing {input_file}...")
    with open(input_file, "r") as f:
        agent_runs = [AgentRun.model_validate(run) for run in json.load(f)]
        client.add_agent_runs(collection_id, agent_runs)
    print(f"Uploaded {len(agent_runs)} runs from {input_file}")

# %%
