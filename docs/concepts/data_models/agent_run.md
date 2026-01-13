# Agent Run

An [`AgentRun`][docent.data_models.agent_run.AgentRun] represents a complete agent run. It contains a collection of [`Transcript`](./transcript.md) objects, as well as metadata (scores, experiment info, etc.).

- In single-agent (most common) settings, each `AgentRun` contains a single `Transcript`.
- In multi-agent settings, an `AgentRun` may contain multiple `Transcript` objects. For example, in a two-agent debate setting, you'll have one `Transcript` per agent in the same `AgentRun`.
- Docent's LLM search features operate over complete `AgentRun` objects. Runs are passed to LLMs in their `.text` form.

### Usage

`AgentRun` objects require a dictionary of [`Transcript`](./transcript.md) objects, as well as a metadata dictionary whose keys are strings. The metadata should be JSON-serializable.

```python
from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import UserMessage, AssistantMessage

transcripts = [
    Transcript(
        messages=[
            UserMessage(content="Hello, what's 1 + 1?"),
            AssistantMessage(content="2"),
        ]
    )
]

agent_run = AgentRun(
    transcripts=transcripts,
    metadata={
        "scores": {"correct": True, "reward": 1.0},
    }
)
```

### Rendering

To see how your `AgentRun` is being rendered to an LLM, you can `print(agent_run.text)`. This might be useful for validating that your metadata is being included properly.

::: docent.data_models.agent_run
