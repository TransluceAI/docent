#%%
# IPython autoreload setup
try:
    from IPython.core.getipython import get_ipython
    ipython = get_ipython()
    if ipython is not None:
        ipython.run_line_magic("load_ext", "autoreload")
        ipython.run_line_magic("autoreload", "2")
except Exception:
    pass  # Not in IPython environment

#%%
# Imports
from uuid import uuid4

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import AssistantMessage, UserMessage
from docent.data_models.transcript import Transcript
from docent.sdk.client import Docent

#%%
# Create a dummy transcript with a simple conversation
transcript = Transcript(
    id=str(uuid4()),
    messages=[
        UserMessage(
            content="Hello, can you help me with a task?",
        ),
        AssistantMessage(
            content="Of course! I'd be happy to help. What would you like me to assist you with?",
        ),
        UserMessage(
            content="Can you explain what an agent run is?",
        ),
        AssistantMessage(
            content="An agent run represents a complete execution trace of an AI agent. "
            "It captures all the interactions, including user messages, assistant responses, "
            "tool calls, and any associated metadata. This allows you to analyze, debug, "
            "and evaluate agent behavior.",
        ),
    ],
    metadata={
        "source": "test_script",
        "version": "1.0",
    },
)

print(f"Created transcript with {len(transcript.messages)} messages")

#%%
# Create a dummy agent run containing the transcript
agent_run = AgentRun(
    id=str(uuid4()),
    name="Test Agent Run",
    description="A dummy agent run created for testing ingestion",
    transcripts=[transcript],
    metadata={
        "test": True,
        "created_by": "mengk",
        "purpose": "testing ingestion flow",
    },
)

print(f"Created agent run: {agent_run.id}")
print(f"  Name: {agent_run.name}")
print(f"  Transcripts: {len(agent_run.transcripts)}")

#%%
# Initialize the Docent client
# This will use credentials from environment or docent.env file
client = Docent(server_url="http://localhost:8905")

#%%
# Create a new collection for testing
collection_id = client.create_collection(name="Test Ingestion Collection")
print(f"Created collection: {collection_id}")

#%%
# Ingest the agent run
result = client.add_agent_runs(
    collection_id=collection_id,
    agent_runs=[agent_run],
    wait=True,  # Wait for ingestion to complete
)

print(f"Ingestion result: {result}")

# %%
