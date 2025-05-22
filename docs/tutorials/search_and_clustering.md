# Search and clustering

!!! note
    🚜 This page is still under construction! 🚜

### Tips for using search

- If you don't precisely know what you're looking for, start with a general search (e.g., "cases of cheating" or "types of environment issues"). Then, based on initial results, refine your query.
- If you *do* know what you're looking for, feel free to provide lots of detail in your query; we use reasoning models to determine whether an agent run matches your query.
- Use appropriate metadata filters to narrow the scope of your search.

### Linking to search results

!!! warning
    We're still ironing out some weird behavior when the base filter changes. You may encounter slowness if you share a completed search result, make the base filter less restrictive, and then open the link.

Search results are persisted and shareable: you can click the share button on both overall results and individual transcript blocks to get shareable links.

<iframe
  width="100%"
  height="375px"
  src="https://www.loom.com/embed/3fe38fcf1efc4970a088ac1f28360534?sid=1c5ed81c-87df-4903-87e3-c0b48e13fc14"
  title="Persisted search results"
  frameborder="0"
  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
  allowfullscreen
></iframe>

### Retrieving search results from the SDK

The Python SDK exposes search results via `get_search_results_for_id`, given a FrameGrid ID (`fg_id`) and Dimension ID (`dim_id`).

```python
results = client.get_search_results_for_id(fg_id, dim_id)
```

If you aren't sure which `fg_id` and `dim_id` to use, you can call `client.list_framegrids()` to find the right FrameGrid, then use `client.list_attribute_searches(fg_id)` to find the right `dim_id` corresponding to your search.

```python
# Find the right FrameGrid
framegrids = client.list_framegrids()
print(framegrids)
fg_id = framegrids[0]["id"]  # An arbitrary FrameGrid

# Find the right dim_id
searches = client.list_attribute_searches(fg_id)
print(searches)
dim_id = searches[0]["dim_id"]  # An arbitrary Dimension
```

You'll get back a list of `Attribute` objects from `get_search_results_for_id`, which might look like:

```
[
    {
        'id': '23daf040-4b78-45d9-a2be-448c0c265275',
        'datapoint_id': '263b8da8-3d30-4d79-9a69-466b695a65cb',
        'attribute': 'agent uses ls',
        'attribute_idx': 0,
        'value': 'In [B2], the agent uses the `ls` command to list the contents of the current directory. This command returns "link.txt", showing there\'s a single text file in the working directory.'
    },
    {
        'id': '9c015cd3-838c-458d-a550-46a7efb6082c',
        'datapoint_id': '56f2d9f1-be00-49dc-b0cb-a1beeccef9b8',
        'attribute': 'agent uses ls',
        'attribute_idx': None,
        'value': None
    },
    ...
]
```
