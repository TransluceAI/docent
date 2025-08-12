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


### Retrieving results from the SDK

The Python SDK exposes rubric results via `get_search_results`, given a Collection ID (`collection_id`), `rubric_id`, and `rubric_version`.

```python
# Get rubric results for a specific rubric and version
rubric_id = "your-rubric-id"
rubric_version = 1
search_results = client.get_search_results(collection_id, rubric_id, rubric_version)
print(search_results)
```

Note that `get_search_results` doesn't run a search, it just retrieves the results from a completed rubric evaluation.

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

    For programmatic access to rubrics, you can use `list_searches` to get a list of rubric objects given a `collection_id`

    ```python
    rubrics = client.list_searches(collection_id)
    print(rubrics)
    rubric_id = rubrics[0]["id"] # An arbitrary rubric
    ```

    You'll get back a list of rubric objects from `list_searches`, which might look like:

    ```
    [
        {
            "id": "590f5bab-5a9c-49ce-bd1b-a7f79b324ae8",
            "collection_id": "e95ad408-9992-43e9-94aa-b0c81536711d",
            "high_level_description": "The user asks a question.",
            "created_at": "2025-06-30T01:46:12.483370",
            "version": 1
        },
        {
            "id": "4a7b48de-29a1-44fa-b245-e2313451e5f9",
            "collection_id": "e95ad408-9992-43e9-94aa-b0c81536711d",
            "high_level_description": "The model runs a python function to decode the contents of a file.",
            "created_at": "2025-06-30T02:04:11.141527",
            "version": 1
        },
        ...
    ]
    ```

To view centroids and corresponding rubric results, call `list_search_clusters` with the `rubric_id` and optional `rubric_version`.

```python
# Get the list of centroids for a given rubric
clusters = client.list_search_clusters(collection_id, rubric_id, rubric_version)
print(clusters)
centroid_id = clusters["centroids"][0]["id"] # A centroid ID
```

You'll get back a list of centroid objects from `list_search_clusters`, which might look like:

```
{
    "centroids": [
        {
            "centroid": "ROT/Caesar Cipher Decryption: Items where the model uses character rotation-based ciphers (like ROT47 or Caesar cipher), which work by shifting each character by a fixed number of positions in the alphabet or ASCII table.",
            "id": "9c03ddb6-9dfa-4dfa-8303-9c3916367616",
            ...
        },
        {
            "centroid": "XOR-based Decryption: Items where the model performs exclusive OR (XOR) operations between the encrypted data and a key/password to reveal the original content.",
            "id": "27edec9b-3309-4c54-b4ee-a759b103129e",
            ...
        },
        ...
    ]
}
```

Finally, use `get_cluster_matches` to see which rubric results match which clusters.

```python
# Get centroid assignments for the rubric
cluster_assignments = client.get_cluster_matches(collection_id, rubric_id, rubric_version)
```
