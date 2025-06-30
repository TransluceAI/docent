# Search and clustering

Use search to find behaviors that you specify in natural language.

### Example walkthrough

Suppose we're curious if there are any issues with the agent scaffolding that are causing failures.

We can start by filtering to runs where the agent failed and searching for `potential issues with the environment the agent is operating in`:

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

- If you don't precisely know what you're looking for, start with a general search (e.g., "cases of cheating" or "types of environment issues"). Then, based on initial results, refine your query.
- If you *do* know what you're looking for, feel free to provide lots of detail in your query; that's why the text box is so large.
- Use appropriate metadata filters to narrow the scope of your search.


### Retrieving results from the SDK

The Python SDK exposes search results via `get_search_results`, given a Collection ID (`collection_id`) and `search_query`.

```python
# Get search results for a specific query id
search_query = "The model runs a python function to decode the contents of a file."
search_results = client.get_search_results(collection_id, search_query)
print(search_results)
```

Note that `get_search_results` doesn't run a search, it just retrieves the results from a completed search on the interface.

```
[
    {
        "id": "b4113df1-b693-4327-a07b-2635719cc582",
        "agent_run_id": "a9016c83-4913-4131-a93b-193455a50be6",
        "search_query": "The model runs a python function to decode the contents of a file.",
        "search_result_idx": 0,
        "value": null
    },
    ...
    {
        "id": "9b37b18a-6951-412c-82e4-68fbb676c667",
        "agent_run_id": "8c8dab17-5ac7-4fe2-a309-0df9d70211fd",
        "search_query": "The model runs a python function to decode the contents of a file.",
        "search_result_idx": 7,
        "value": "In [T0B49], the model makes a final attempt to decode the encrypted file using \"mynewxorpad\" as the key in its XOR decryption function."
    }
]
```

If you aren't sure which `collection_id` to use, you can call `client.list_collections()` to find the right Collection.

```python
# Find the right Collection
collections = client.list_collections()
print(collections)
collection_id = collections[0]["id"]  # An arbitrary Collection
```

??? note "How to get search queries for the current Collection"

    For programmatic access to search queries, you can use `list_searches` to get a list of query objects given a `collection_id`

    ```python
    search_queries = client.list_searches(collection_id)
    print(search_queries)
    search_query = search_queries[1]["search_query"] # An arbitrary query
    ```

    You'll get back a list of `SQLASearchQuery` rows from `list_searches`, which might look like:

    ```
    [
        {
            "id": "590f5bab-5a9c-49ce-bd1b-a7f79b324ae8",
            "collection_id": "e95ad408-9992-43e9-94aa-b0c81536711d",
            "search_query": "The user asks a question.",
            "created_at": "2025-06-30T01:46:12.483370"
        },
        {
            "id": "4a7b48de-29a1-44fa-b245-e2313451e5f9",
            "collection_id": "e95ad408-9992-43e9-94aa-b0c81536711d",
            "search_query": "The model runs a python function to decode the contents of a file.",
            "created_at": "2025-06-30T02:04:11.141527"
        },
        ...
    ]
    ```

To view clusters and corresponding search results, call `list_search_clusters` with the `search_query`.

```python
# Get the list of clusters for a given query id
clusters = client.list_search_clusters(collection_id, search_query)
print(clusters)
centroid = clusters[0]["centroid"] # A centroid description
```

You'll get back a list of cluster objects from `list_search_clusters`, which might look like:

```
[
    {
        "centroid": "ROT/Caesar Cipher Decryption: Items where the model uses character rotation-based ciphers (like ROT47 or Caesar cipher), which work by shifting each character by a fixed number of positions in the alphabet or ASCII table.",
        "id": "9c03ddb6-9dfa-4dfa-8303-9c3916367616"
    },
    {
        "centroid": "XOR-based Decryption: Items where the model performs exclusive OR (XOR) operations between the encrypted data and a key/password to reveal the original content.",
        "id": "27edec9b-3309-4c54-b4ee-a759b103129e"
    },
    ...
]
```

Finally, get the search results for the cluster with `get_cluster_matches` and the `centroid` description.

```python
# Same objects as get_search_results
cluster_search_result_matches = client.get_cluster_matches(collection_id, centroid)
```
