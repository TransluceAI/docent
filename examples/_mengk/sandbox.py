# pyright: ignore
# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")
IPython.get_ipython().run_line_magic("autoreload", "2")

# %%

from docent import DocentClient

client = DocentClient(server_url="http://localhost:8889", web_url="http://localhost:3001")

fg_id = client.create_framegrid(
    name="sample framegrid", description="example that comes with the Docent repo"
)

transcript_1 = [
    {"role": "user", "content": "What's the weather like in New York today?"},
    {
        "role": "assistant",
        "content": "The weather in New York today is mostly sunny with a high of 75°F (24°C).",
    },
]
metadata_1 = {"model": "gpt-3.5-turbo", "agent_scaffold": "foo", "hallucinated": True}
transcript_2 = [
    {"role": "user", "content": "What's the weather like in San Francisco today?"},
    {
        "role": "assistant",
        "content": "The weather in San Francisco today is mostly cloudy with a high of 65°F (18°C).",
    },
]
metadata_2 = {"model": "gpt-3.5-turbo", "agent_scaffold": "foo", "hallucinated": True}
transcript_3 = [
    {"role": "user", "content": "What's the weather like in Paris today?"},
    {
        "role": "assistant",
        "content": "I'm sorry, I don't know because I don't have access to weather tools.",
    },
]
metadata_3 = {"model": "gpt-3.5-turbo", "agent_scaffold": "bar", "hallucinated": False}

transcripts = [transcript_1, transcript_2, transcript_3]
metadata = [metadata_1, metadata_2, metadata_3]


from docent.data_models import Transcript
from docent.data_models.chat import parse_chat_message

parsed_transcripts = [
    Transcript(messages=[parse_chat_message(msg) for msg in transcript])
    for transcript in transcripts
]


from pydantic import Field

from docent.data_models import BaseAgentRunMetadata


class MyMetadata(BaseAgentRunMetadata):
    model: str = Field(description="LLM API model used to generate the transcript")
    agent_scaffold: str = Field(description="Agent scaffold in which the agent was run")


from docent.data_models import AgentRun

agent_runs = [
    AgentRun(
        transcripts={"default": t},
        metadata=MyMetadata(
            model=m["model"],
            agent_scaffold=m["agent_scaffold"],
            scores={"hallucinated": m["hallucinated"]},
            default_score_key="hallucinated",
        ),
    )
    for t, m in zip(parsed_transcripts, metadata)
]
client.add_agent_runs(fg_id, agent_runs)
# %%
