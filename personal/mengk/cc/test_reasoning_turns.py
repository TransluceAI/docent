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
from docent.data_models.agent_run import AgentRun
from docent.data_models.transcript import Transcript
from docent.data_models.chat.message import parse_chat_message
from docent.data_models.chat.content import ContentReasoning, ContentText
from docent.sdk.client import Docent

#%%
# Generate sample user/assistant turns with reasoning

messages_data = [
    {
        "role": "system",
        "content": "You are a helpful assistant that thinks step by step.",
    },
    {
        "role": "user",
        "content": "What is the capital of France?",
    },
    {
        "role": "assistant",
        "content": [
            {
                "type": "reasoning",
                "reasoning": "The user is asking about the capital of France. This is a straightforward geography question. France is a country in Western Europe, and its capital city is Paris. Paris is known for landmarks like the Eiffel Tower, the Louvre Museum, and Notre-Dame Cathedral.",
            },
            {
                "type": "text",
                "text": "The capital of France is Paris.",
            },
        ],
    },
    {
        "role": "user",
        "content": "What about Germany?",
    },
    {
        "role": "assistant",
        "content": [
            {
                "type": "reasoning",
                "reasoning": "Now the user is asking about Germany's capital. Germany is also in Western Europe. Its capital is Berlin. I should note that before German reunification in 1990, West Germany's capital was Bonn, but since reunification, Berlin has been the capital of unified Germany.",
            },
            {
                "type": "text",
                "text": "The capital of Germany is Berlin.",
            },
        ],
    },
    {
        "role": "user",
        "content": "Can you solve this math problem: 2 + 2 * 3?",
    },
    {
        "role": "assistant",
        "content": [
            {
                "type": "reasoning",
                "reasoning": "This is a math problem that tests order of operations (PEMDAS/BODMAS). According to the order of operations, multiplication should be performed before addition.\n\nStep 1: First, calculate 2 * 3 = 6\nStep 2: Then, calculate 2 + 6 = 8\n\nSo the answer is 8, not 12 (which would be wrong if we added first).",
            },
            {
                "type": "text",
                "text": "Following the order of operations (multiplication before addition):\n\n2 + 2 * 3 = 2 + 6 = 8",
            },
        ],
    },
]

# Parse messages using parse_chat_message
messages = [parse_chat_message(msg) for msg in messages_data]

#%%
# Create a transcript with the messages
transcript = Transcript(
    name="Geography and Math Q&A",
    description="A conversation about capitals and math",
    messages=messages,
    metadata={
        "topic": "educational",
        "has_reasoning": True,
    },
)

#%%
# Create an agent run with the transcript
agent_run = AgentRun(
    name="Test Agent Run with Reasoning",
    description="Testing user/assistant turns with reasoning content",
    transcripts=[transcript],
    metadata={
        "test_type": "reasoning_test",
        "model": "test-model",
        "created_by": "mengk",
    },
)

#%%
# Preview the agent run structure
print("Agent Run ID:", agent_run.id)
print("Transcript ID:", transcript.id)
print("Number of messages:", len(messages))

# Check that reasoning is preserved
for i, msg in enumerate(messages):
    print(f"\nMessage {i} ({msg.role}):")
    if hasattr(msg, "content") and isinstance(msg.content, list):
        for content in msg.content:
            if isinstance(content, ContentReasoning):
                print(f"  [Reasoning]: {content.reasoning[:50]}...")
            elif isinstance(content, ContentText):
                print(f"  [Text]: {content.text[:50]}...")
    else:
        content_preview = msg.text[:50] if msg.text else "(empty)"
        print(f"  {content_preview}...")

#%%
# Upload to Docent
# Make sure you have a docent.env file or DOCENT_API_KEY environment variable set

client = Docent(server_url="http://localhost:8902")

#%%
# Create a new collection
collection_id = client.create_collection(name="Reasoning Test Collection")

#%%
# Add the agent run to the collection
result = client.add_agent_runs(
    collection_id=collection_id,
    agent_runs=[agent_run],
)

print("Upload result:", result)

#%%
# Open the agent run in the browser
client.open_agent_run(collection_id, agent_run.id)

# %%
