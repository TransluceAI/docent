# Search and clustering

Docent allows you to search for specific behaviors in agent runs. We refer to search queries as *rubrics*, which specify what kinds of results you are looking for. Your rubrics can be arbitrarily complex, since we use frontier-level language models to evaluate them.

### Walkthrough

Let's check for issues with the agent scaffolding that might have caused spurious failures.

First, we filter to runs where the agent failed, then search for `potential issues with the environment the agent is operating in`:


<video controls autoplay loop width="100%">
  <source src="https://transluce-videos.s3.us-east-1.amazonaws.com/docent-docs/search-compressed.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>

We can then cluster the results and see what the most common issues are:

<video controls autoplay loop width="100%">
  <source src="https://transluce-videos.s3.us-east-1.amazonaws.com/docent-docs/clustering-compressed.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>

### Sharing results

You can open access permissions to share these results with anyone:

<video controls autoplay loop width="100%">
  <source src="https://transluce-videos.s3.us-east-1.amazonaws.com/docent-docs/sharing-general-compressed.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>

You can also link to specific parts of the agent run:

<video controls autoplay loop width="100%">
  <source src="https://transluce-videos.s3.us-east-1.amazonaws.com/docent-docs/sharing-specific-compressed.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>

### Tips for using search

- If you don't precisely know what you're looking for, start with a general rubric (e.g., "cases of cheating" or "types of environment issues"). Then, based on initial results, refine your rubric.
- If you *do* know what you're looking for, feel free to provide lots of detail in your rubric; that's why the text box is so large.
- Use appropriate metadata filters to narrow the scope of your search.

### Customizing the judge output schema

Judges produce data in a JSON format. Each judge has an associated schema that is used to prompt the language model and validate its output. The default schema is:

```json
{
    "type": "object",
    "properties": {
        "explanation": {
          "type": "string",
          "citations": true
        },
        "label": {
          "type": "string",
          "enum": ["match", "no match"]
        },
    }
}
```

You can edit this schema in the rubric editor. For example, if you want the judge to classify transcripts into one of three categories, you can put those categories in `properties.label.enum`. See the [JSON Schema documentation](https://json-schema.org/learn/getting-started-step-by-step) for more information on how to write a schema.

`"citations"` is a non-standard keyword which indicates whether a string property should include citations to a run's transcript(s). If any part of the schema uses citations, the judge model will receive a prompt about how to write them. Citations are rendered as clickable links.

### Retrieving results from the SDK

The Python SDK exposes rubric results via `get_rubric_run_state`, given a Collection ID (`collection_id`) and `rubric_id`.

```python
# Get rubric run state for a specific rubric
rubric_id = "your-rubric-id"
run_state = client.get_rubric_run_state(collection_id, rubric_id)
print(run_state)
```

Note that `get_rubric_run_state` doesn't run a search, it just retrieves the results from a completed rubric evaluation along with job status and total agent runs.

```
{
    "results": [
        {
            "id": "b4113df1-b693-4327-a07b-2635719cc582",
            "agent_run_id": "a9016c83-4913-4131-a93b-193455a50be6",
            "rubric_id": "your-rubric-id",
            "rubric_version": 1,
            "value": null
        },
        ...
        {
            "id": "9b37b18a-6951-412c-82e4-68fbb676c667",
            "agent_run_id": "8c8dab17-5ac7-4fe2-a309-0df9d70211fd",
            "rubric_id": "your-rubric-id",
            "rubric_version": 1,
            "value": "In [T0B49], the model makes a final attempt to decode the encrypted file using \"mynewxorpad\" as the key in its XOR decryption function."
        }
    ]
}
```

If you aren't sure which `collection_id` to use, you can call `client.list_collections()` to find the right Collection.

```python
# Find the right Collection
collections = client.list_collections()
print(collections)
collection_id = collections[0]["id"]  # An arbitrary Collection
```

??? note "How to get rubrics for the current Collection"

    For programmatic access to rubrics, you can use `list_rubrics` to get a list of rubric objects given a `collection_id`

    ```python
    rubrics = client.list_rubrics(collection_id)
    print(rubrics)
    rubric_id = rubrics[0]["id"] # An arbitrary rubric
    ```

To view centroids and corresponding rubric results, call `get_clustering_state` with the `rubric_id`.

```python
# Get the clustering state for a given rubric
clustering_state = client.get_clustering_state(collection_id, rubric_id)
print(clustering_state)
centroid_id = clustering_state["centroids"][0]["id"] # A centroid ID
```

You can also get just the centroids using the convenience method:

```python
# Get just the centroids for a given rubric
centroids = client.get_cluster_centroids(collection_id, rubric_id)
print(centroids)
```

Finally, use `get_cluster_assignments` to see which rubric results match which clusters.

```python
# Get centroid assignments for the rubric
cluster_assignments = client.get_cluster_assignments(collection_id, rubric_id)
```
