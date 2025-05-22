# Metadata

This module provides base metadata classes, used with [`AgentRun`](./agent_run.md) and [`Transcript`](./transcript.md) objects.

Any [`BaseMetadata`][docent.data_models.metadata.BaseMetadata] subclass **must be JSON serializable**. There is a validator that checks for compliance.

[`BaseAgentRunMetadata`][docent.data_models.metadata.BaseAgentRunMetadata] is an extension of `BaseMetadata` that requires `run_id`, `scores`, and a `default_score_key`. The scoring fields are useful for tracking metrics, like task completion or reward. All `AgentRun` objects require these fields, but `Transcript` objects don't.

### Accessing metadata

#### Values

Use the `get()` method for safer access to metadata values:

```python
value = metadata.get("field_name")  # Returns None if missing
value = metadata.get("field_name", default_value="fallback")  # Custom default
value = metadata.get("field_name", raise_if_missing=True)  # Raises if missing
```

#### Descriptions

Retrieve field descriptions using:

```python
desc = metadata.get_field_description("field_name")  # Single field
all_descs = metadata.get_all_field_descriptions()  # All fields
```

### Subclassing metadata classes

You can create custom metadata classes (e.g., to store arbitrary evaluation data or training information) by subclassing `BaseMetadata` or `BaseAgentRunMetadata`:

```python
from pydantic import Field
from docent.data_models import BaseAgentRunMetadata

class RLTrainingMetadata(BaseAgentRunMetadata):
    episode: int = Field(description="Training episode number")
    policy_version: str = Field(description="Version of the policy used")
    training_step: int = Field(description="Global training step")
```

!!! note
    As demonstrated above, we recommend using `pydantic.Field` to add field descriptions, which are passed to LLMs to help them better answer your questions.

You can then populate your custom metadata class as such:

```python
metadata = RLTrainingMetadata(
    # Required fields
    run_id="run_1",
    scores={"reward_1": 0.1, "reward_2": 0.5, "reward_3": 0.8},
    default_score_key="reward_1",
    # Custom fields
    episode=42,
    policy_version="v1.2.3",
    training_step=12500,
)
```

::: docent.data_models.metadata
