# Metadata

The [`AgentRun`](./agent_run.md) and [`Transcript`](./transcript.md) objects both take in `metadata` fields, which should be of the form `dict[str, Any]`.

Any metadata **must be JSON serializable**. There is a validator that checks for compliance. We use the Pydantic serializer, which is quite general (e.g. can serialize any Pydantic model or standard Python collection, and can also handle nesting).

We recommend including information about metrics / scores in the metadata, as well as other information about the agent or task setup.

The scoring fields are useful for tracking metrics, like task completion or reward. All `AgentRun` objects require these fields, but `Transcript` objects don't.

Here's an example of what a typical metadata might look like:

```python
metadata = {
    # Required fields
    "scores": {"reward_1": 0.1, "reward_2": 0.5, "reward_3": 0.8},
    # Custom fields
    "episode": 42,
    "policy_version": "v1.2.3",
    "training_step": 12500,
}
```


If you're using Inspect, `docent.loaders.load_inspect` also contains a `load_inspect_log` function which reads the standard scoring and metadata information from Inspect logs and copies them into Docent metadata.
