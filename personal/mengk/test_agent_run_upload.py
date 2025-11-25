# autoflake: skip_file
# pyright: ignore

# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")  # type: ignore
IPython.get_ipython().run_line_magic("autoreload", "2")  # type: ignore

# %%

from docent import Docent
from docent_core._env_util import ENV

DOCENT_API_KEY = ENV.get("DOCENT_API_KEY")
DOCENT_DOMAIN = ENV.get("DOCENT_DOMAIN")
if not DOCENT_DOMAIN or not DOCENT_API_KEY:
    raise ValueError("DOCENT_API_KEY and DOCENT_DOMAIN must be set")
dc = Docent(api_key=DOCENT_API_KEY, domain=DOCENT_DOMAIN, server_url="http://localhost:8890")

# %%

from inspect_ai.log import EvalLog, read_eval_log
from pydantic_core import to_jsonable_python

# Load Inspect AI sample log
from docent.samples import get_inspect_fpath

ctf_log = read_eval_log(get_inspect_fpath())
ctf_log_dict = to_jsonable_python(ctf_log)

print(f"Loaded Inspect log with {len(ctf_log.samples or [])} samples")

# %%

# Convert Inspect log to AgentRun objects
from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import parse_chat_message


def load_inspect_log(log: EvalLog) -> list[AgentRun]:
    if log.samples is None:
        return []

    agent_runs: list[AgentRun] = []

    for s in log.samples:
        # Extract sample_id from the sample ID
        sample_id = s.id
        epoch_id = s.epoch

        # Gather scores
        scores: dict[str, int | float | bool] = {}

        # Evaluate correctness (for this CTF benchmark)
        if s.scores and "includes" in s.scores:
            scores["correct"] = s.scores["includes"].value == "C"

        # Set metadata
        metadata = {
            "task_id": log.eval.task,
            "sample_id": str(sample_id),
            "epoch_id": epoch_id,
            "model": log.eval.model,
            "scores": scores,
            "additional_metadata": s.metadata,
            "scoring_metadata": s.scores,
        }

        # Create transcript
        agent_runs.append(
            AgentRun(
                transcripts=[
                    Transcript(messages=[parse_chat_message(m.model_dump()) for m in s.messages])
                ],
                metadata=metadata,
            )
        )

    return agent_runs


agent_runs = load_inspect_log(ctf_log)
print(f"Created {len(agent_runs)} AgentRun objects")

# %%

# Preview the first agent run
if agent_runs:
    print("First agent run preview:")
    print(
        agent_runs[0].text[:2000] + "..." if len(agent_runs[0].text) > 2000 else agent_runs[0].text
    )

# %%

# Create a test collection and upload agent runs
collection_id = dc.create_collection(
    name="Test Inspect Upload",
    description="Testing agent run upload from Inspect AI logs",
)
print(f"Created collection: {collection_id}")

# %%

# Upload agent runs to the collection
dc.add_agent_runs(collection_id, agent_runs)
print(f"Successfully uploaded {len(agent_runs)} agent runs to collection {collection_id}")

# %%

# Verify the upload by listing collections
collections = dc.list_collections()
print("Collections:")
for c in collections:
    print(f"  - {c}")

# %%
# =============================================================================
# Alternative: Using AgentRunWriter for non-blocking uploads
# =============================================================================

# %%

import docent

# Initialize the AgentRunWriter - this creates a background thread for async uploads
writer = docent.init(
    collection_name="Test AgentRunWriter Upload",
    api_key=DOCENT_API_KEY,
    server_url="http://localhost:8890",
    web_url=f"http://{DOCENT_DOMAIN}",
    # Optional: customize writer behavior
    num_workers=2,
    queue_maxsize=20_000,
    flush_interval=1.0,
    batch_size=1_000,
)

# %%

# Log agent runs using the non-blocking writer
# This returns immediately and uploads happen in the background
writer.log_agent_runs(agent_runs)
print(f"Queued {len(agent_runs)} agent runs for background upload")

# %%

# When done, call finish() to wait for pending uploads to complete
# Use force=True to shut down immediately without waiting
writer.finish(force=False)
print("AgentRunWriter finished uploading all queued runs")

# %%
