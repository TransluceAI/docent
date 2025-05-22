# Agent Run

An [`AgentRun`][docent.data_models.agent_run.AgentRun] represents a complete agent run. It contains a collection of [`Transcript`](./transcript.md) objects, as well as metadata (scores, experiment info, etc.).

- In single-agent (most common) settings, each `AgentRun` contains a single `Transcript`.
- In multi-agent settings, an `AgentRun` may contain multiple `Transcript` objects. For example, in a two-agent debate setting, you'll have one `Transcript` per agent in the same `AgentRun`.
- Docent's LLM search features operate over complete `AgentRun` objects. Runs are passed to LLMs in their `.text` form.

### Usage

`AgentRun` objects require a dictionary of [`Transcript`](./transcript.md) objects, as well as a [`BaseAgentRunMetadata`](./metadata.md) object. In the base metadata object, you must specify a `run_id`, `scores`, and a `default_score_key`.

```python
from docent.data_models import AgentRun, Transcript, BaseAgentRunMetadata
from docent.data_models.chat import UserMessage, AssistantMessage

transcripts = {
    "default": Transcript(
        messages=[
            UserMessage(content="Hello, what's 1 + 1?"),
            AssistantMessage(content="2"),
        ]
    )
}

agent_run = AgentRun(
    transcripts=transcripts,
    metadata=BaseAgentRunMetadata(
        run_id="run_1",
        scores={"correct": True, "reward": 1.0},
        default_score_key="correct",
    )
)
```

If you want to add additional fields to your metadata, see [here for instructions on subclassing](./metadata.md#subclassing-metadata-classes).

### Rendering

To see how your `AgentRun` is being rendered to an LLM, you can `print(agent_run.text)`. This might be useful for validating that your metadata is being included properly.

::: docent.data_models.agent_run
