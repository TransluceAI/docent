# Filters and dimensions

This module defines a filtering system for agent runs in Docent. Filters provide a flexible way to select
specific agent runs based on various criteria.

### Filter Types

- [`PrimitiveFilter`][docent.data_models.filters.PrimitiveFilter]: Filter agent runs by any primitive operator. These can be run in SQL.
- [`AttributePredicateFilter`][docent.data_models.filters.AttributePredicateFilter]: Use LLMs to determine if an agent run's attributes satisfy a given natural language predicate.
- [`AttributeExistsFilter`][docent.data_models.filters.AttributeExistsFilter]: Check if an agent run has a given attribute.
- [`ComplexFilter`][docent.data_models.filters.ComplexFilter]: Combine filters with AND/OR. This can be run in SQL if all its filters are primitive.
- [`AgentRunIdFilter`][docent.data_models.filters.AgentRunIdFilter]: Filter agent runs by their ID.

### Usage

Filters are to be defined, then applied to data. For example, we can define a filter that selects successful agent runs with "error" text:

```python
# Find agent runs with high accuracy AND containing "error" text
filter = ComplexFilter(
    filters=[
        PrimitiveFilter(
            key_path=("metadata", "scores", "correct"),
            value=True,
            op="=="
        ),
        PrimitiveFilter(
            key_path=("text",),
            value="error",
            op="~*"
        )
    ],
    op="and"
)
```

Then, we can apply the filter to a list of agent runs:

```python
# Apply a filter to agent runs
judgments = await filter.apply(agent_runs)

# Get matching agent runs
matching_runs = [ar for ar, j in zip(agent_runs, judgments) if j.matches]
```

Filters return a list of [`Judgment`][docent.data_models.filters.Judgment] objects, which contain the agent run, metadata about where the filter was applied, and data on whether/why the filter matched.

::: docent.data_models.filters
