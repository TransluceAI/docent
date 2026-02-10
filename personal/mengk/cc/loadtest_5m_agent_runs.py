#%%
# IPython autoreload setup
try:
    from IPython import get_ipython
    ipython = get_ipython()
    if ipython is not None:
        ipython.run_line_magic("load_ext", "autoreload")
        ipython.run_line_magic("autoreload", "2")
except Exception:
    pass  # Not in IPython environment

#%%
import random
import string
from uuid import uuid4

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import UserMessage
from docent.data_models.transcript import Transcript
from docent.sdk.client import Docent

#%%
# Initialize client
client = Docent()

#%%
# Create a new collection for the load test
collection_id = client.create_collection(name="Load Test 5M Agent Runs")
print(f"Collection ID: {collection_id}")

#%%
# Helper to generate a simple AgentRun
def make_agent_run() -> AgentRun:
    random_text = "".join(random.choices(string.ascii_letters + string.digits, k=64))
    return AgentRun(
        id=str(uuid4()),
        name=f"run-{random_text[:8]}",
        transcripts=[
            Transcript(
                messages=[
                    UserMessage(content=f"Hello, here is a random message: {random_text}"),
                ]
            )
        ],
    )

#%%
# Upload 5M agent runs in batches of 10,000
TOTAL_RUNS = 5_000_000
BATCH_SIZE = 10_000

for batch_start in range(0, TOTAL_RUNS, BATCH_SIZE):
    batch_end = min(batch_start + BATCH_SIZE, TOTAL_RUNS)
    batch = [make_agent_run() for _ in range(batch_end - batch_start)]
    print(f"Uploading batch {batch_start // BATCH_SIZE + 1} ({batch_start}–{batch_end})...")
    client.add_agent_runs(collection_id, batch, wait=False)

print(f"Done! Submitted {TOTAL_RUNS} agent runs to collection {collection_id}")
