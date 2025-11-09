#%%

from docent import Docent

DOCENT_API_KEY="dk_OAsemTbrmXIonGIk_76PQIMTadPq3iA80txM9j1ZNYXk410MZsMZMnOvUQs2ZGM"
DOCENT_TRACING_ENDPOINT="https://api.docent-bridgewater.transluce.org/rest/telemetry"
DOCENT_API_URL="https://api.docent-bridgewater.transluce.org"
# DOCENT_COLLECTION_ID="aedca6e5-34ec-4edb-b97b-403fc2aff3ae"  # overnight
# DATASET_FILE="clinical_trials_benchmark_2025_gitignore.json"
DOCENT_COLLECTION_ID="c1ecffe7-9f5b-459b-b70a-e8435ed7686e"  # kalshi-liquid
DATASET_FILE="kalshi-binary-liquid-25-04-02-25-05-23_gitignore.json"

dc = Docent(api_key=DOCENT_API_KEY, server_url=DOCENT_API_URL)

#%%

import json
with open(DATASET_FILE, "r") as f:
    data = json.load(f)

#%%

from pprint import pprint
q_to_resolution = {}
for qo in data[0]["ForecasterBinaryBenchmarkInputs"]["questions"]:
    qo = qo["ForecastBinaryBenchmarkQuestion"]
    q = qo["question"]
    resolved_to = qo["resolved_to"]
    q_to_resolution[q] = resolved_to

len(q_to_resolution)

# %%

dr = dc.execute_dql(DOCENT_COLLECTION_ID, """
SELECT a.id, a.metadata_json ->> 'question' FROM agent_runs a
WHERE a.metadata_json ->> 'gold_probability' IS NULL
""")
cols, rows = dr["columns"], dr["rows"]

# %%

arid_to_resolution = {}

for row in rows:
    arid, q = row
    if q is None:
        continue
    resolution = q_to_resolution[q]
    arid_to_resolution[arid] = resolution

len(arid_to_resolution)

# %%

from docent.trace import agent_run_context, agent_run_metadata, initialize_tracing
from tqdm.auto import tqdm
import anyio

initialize_tracing(collection_id=DOCENT_COLLECTION_ID, endpoint=DOCENT_TRACING_ENDPOINT, api_key=DOCENT_API_KEY)

async def process_agent_run(arid: str, resolution: float, semaphore: anyio.Semaphore, pbar: tqdm):
    async with semaphore:
        async with agent_run_context(agent_run_id=arid):
            agent_run_metadata(metadata={"gold_probability": resolution})
        pbar.update(1)

async def process_all():
    semaphore = anyio.Semaphore(50)  # Limit to 10 concurrent tasks
    items = list(arid_to_resolution.items())
    with tqdm(total=len(items)) as pbar:
        async with anyio.create_task_group() as tg:
            for arid, resolution in items:
                tg.start_soon(process_agent_run, arid, resolution, semaphore, pbar)

await process_all()

# %%

dr = dc.execute_dql(DOCENT_COLLECTION_ID, """
SELECT a.id FROM agent_runs a
WHERE
    a.metadata_json ->> 'gold_probability' IS NULL AND
    a.metadata_json ->> 'question' IS NOT NULL 
""")
cols, rows = dr["columns"], dr["rows"]
len(rows)
# %%
