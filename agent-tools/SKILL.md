---
name: analysis
description: Docent is a platform for analyzing AI agent behavior using large language models. Use this skill anytime you want to use Docent to analyze AI agent behavior.
alwaysApply: true
---

# Docent Analysis Guide

You can interact with Docent by writing Python scripts that use the Docent SDK, and by calling Docent MCP tools. If Docent MCP tools are not available, alert the user that the Docent MCP server is not installed correctly.

## Data models and key concepts
* A transcript is a sequence of messages from the system, the agent (aka assistant), the user, and/or tools that the agent calls.
* An agent run represents an AI agent attempting a task or interacting with a user. An agent run may contain one or more transcripts.
* A collection contains agent runs from a certain experiment or benchmark. When we query, analyze, or compare agent runs, we do so within one collection at a time.

## High-level analysis approach
The Docent SDK facilitates two main technqiues:
* LLMRequest, to have LLMs read transcripts and perform qualitative analysis
* DQL, to query and aggregate data already in the database (e.g. metadata that was logged with agent runs and transcripts, previous analysis results)

Sometimes, the user's request will clearly pertain to one of these technqiues. Other times, the user may instead ask high-level questions about the behavior of their AI agents, and you will have to investigate. In the latter case, the following general process is recommended:

1. Use the `get_metadata_fields` MCP tool to understand the structure of agent run metadata for the current collection.
2. If the metadata fields might shed light on the user's question, you may use DQL to query the metadata. You may do this autonomously without consulting the user.
3. After querying the metadata, you must decide whether qualitative analysis (reading the transcripts) would provide further insight. If it seems appropriate, create a plan to perform the analysis using LLMRequest. Feel free to ask the user clarifying questions. You must let the user review your plan before you proceed. Then write a script to implement the plan, and run it.

## Analysis guidelines and reminders
* If the user asks you to "summarize the agent runs", "classify the results", or similar, they do not necessarily mean that you (the coding agent) should do so directly. In most cases, it is better to use the Docent SDK to submit an LLM analysis request. Then you may open the results of that analysis to show the user.
* Agent runs contain metadata. Metadata varies by collection. Do not make assumptions about the structure of run metadata. Use the `get_metadata_fields` MCP tool to find out.
* If you are writing code that will submit LLMRequests, you are encouraged to write it out as a script so you can improve and re-use it later. Unless otherwise instructed, you may place analysis scripts in the current working directory. Quick DQL queries can be done in scripts or inline with the Bash tool at your discretion.
* Unless informed otherwise, assume uv is used for python package management. Run your scripts with `uv run`.
* If you're not sure what collection the user is talking about, refer to the docent.env file in the working directory. If it does not exist, or if it does not include DOCENT_COLLECTION_ID, ask the user to paste the collection UUID.
* When writing code to perform analysis, Don't Repeat Yourself. This is particularly important when it comes to prompts for LLMs. The user will likely want to modify prompts, and they should not have to track down multiple copies of a prompt throughout your code. If you need to create different variants of a prompt, build them from reusable pieces and/or use string interpolation, so there is a single source of truth for each part of the prompt.
* When writing code to perform analysis, keep variable names generic. For example, if you are comparing the performance of two models, you might refer to them as "model_a" and "model_b" in your code, and then declare the identity of these models in one place only. This makes your code more reusable, so we can perform the same analysis on other data.
* When writing code to perform analysis, be sparing with print statements. In many cases a simple success/failure message at the end is enough.
* If you are analyzing a limited sample of many items (e.g. because you can only fit so many in the context window), be mindful of *how* you are sampling them. The most recent N items may be a biased sample. It is safe to assume that UUIDs are random.
* Metadata alone may provide an incomplete picture. Don't forget to consider qualitative analysis!
* The user must approve all plans for LLMRequest analysis. If the user tells you how to perform the analysis, that counts as approval. If you use your own judgement in planning the analysis, you must present your plan to the user for approval before implementing it.

## Building LLMRequests with the Prompt API

The Docent SDK can be installed via `docent-python` (e.g., `uv add docent-python`).

Start with these imports when using the Docent SDK:
```python
from docent.sdk.client import Docent
from docent.sdk.llm_request import LLMRequest, ExternalAnalysisResult
from docent.sdk.llm_context import Prompt, AgentRunRef, ResultRef

client = Docent()
```

Note: the Docent SDK will automatically discover and load a docent.env file if it exists. You do not need to explicitly source docent.env.

The `Prompt` class takes a list of strings and context item refs. Context items are agent runs, transcripts, and analysis results. You can reference items in a prompt without fetching their full content.

```python
run = AgentRunRef(id="<uuid>", collection_id="<uuid>")
transcript = TranscriptRef(id="<uuid>", agent_run_id="<uuid>", collection_id="<uuid>")
result = ResultRef(id="<uuid>", result_set_id="<uuid>", collection_id="<uuid>")

request = LLMRequest(
    prompt=Prompt([run, "Summarize this run."]),
    metadata={"summarized_run_id": run.id}
)
```

A prompt may include multiple context items of different types, which is useful for comparing behavior across runs and looking for recurring patterns.

When the same ref appears multiple times in a single prompt, the first occurrence renders as full content alongside an alias, and subsequent occurrences render as just the alias.

A useful pattern is to use DQL to get the IDs of relevant runs, then iterate over those run IDs to build the prompts for the language model.

Remember that the context window of the LLM is limited. Avoid passing more than a few full agent runs in a single prompt. However, it is fine to pass many LLMRequests to a single result set, since each request is processed separately.

### Writing a good prompt

The quality of LLM output depends on the quality the prompt you write for the LLMRequest. The LLM knows it is analyzing agent run transcripts, and knows how to cite items in its context. You can ask the LLM to cite items in its context and it will just work without further guidance. Otherwise, you are responsible for understanding the purpose of the LLMRequest and writing a clear prompt articulating what you want the LLM to do.

* Include any information about the runs that is not obvious from the transcripts but important for analyzing them appropriately
* How detailed or brief should output be? A short paragraph is a good default, but it depends on the nature of the analysis.
* If you're asking for extensive (multi-paragraph) response, how should it be structured? Note: markdown is supported
* If you are looking for a particular behavior, how exactly is that behavior defined? If you're proposing a specific definition, make sure the user signs off on it.
* If you are asking the LLM to analyze other analysis results, remind it to cite those analysis results, NOT the original transcripts which the results may refer to.

### Submitting Requests for Backend Processing

Use `submit_llm_requests()` to have the backend process your requests:

```python
result = client.submit_llm_requests(
    collection_id="<collection-uuid>",
    requests=[request1, request2, ...], # if submitting multiple requests, send them in a batch, not one-at-a-time
    model_string="openai/gpt-5-mini", # pass a model explicitly, use this one by default
    result_set_name="cheating/v1",  # hierarchical naming
)
```

Use hierarchical names with `/` separators for organization. It's often good to have a component like `v1`, `v2`, etc. so you can iterate on your methodology and compare results.

Important: Do not use openai/gpt-4o or openai/gpt-4o-mini. Those models are obsolete and superseded by openai/gpt-5 and openai/gpt-5-mini respectively.

### Structured Output

By default, each LLMRequest will produce a text response. If you need more structured output, you can pass a JSON schema when you create a result set. All results in a result set must have the same output schema. Keep things simple and do not request more fields than you need.

Output schemas can have string, number, and boolean properties. They should not have nested objects or arrays.

```python
result = client.submit_llm_requests(
    collection_id="<uuid>",
    requests=[request],
    result_set_name="classification/v1",
    output_schema={
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": ["helpful", "harmful", "neutral"]},
            "confidence": {"type": "number"},
            "reasoning": {"type": "string"}
        },
        "required": ["category", "confidence", "reasoning"]
    }
)
```


### Presenting Results

Once a batch of LLM requests is submitted, open the result set in the browser. Do not wait for a request to finish to open the results. To open a Docent URL in the browser, use the `navigate_to` tool from the Docent MCP server.

Do not attempt to interact with the Docent web UI using other browsing tools.

By default, let user view the results and draw their own conclusion. If asked to draw a conclusion, you may fetch and read results. Never draw conclusions from LLMRequest analysis without reading the results.

### Retrieving Results programmatically

You can retrieve results programmatically if you need to process them further (e.g. make a chart, or pass them to another LLMRequest).

Note the browser is the preferred way to view results. Only retrieve results programmatically if you need to process them further. Do not retrieve results for presentation to the user, unless the user specifically requests.

```python
# List all result sets (optionally filtered by prefix)
sets = client.list_result_sets(collection_id, prefix="analysis/")

# Get result set metadata
result_set = client.get_result_set(collection_id, "analysis/experiment_1")

# Get results as DataFrame
df = client.get_result_set_dataframe(
    collection_id,
    "analysis/experiment_1",
)
```

# DQL (Docent Query Language)

Docent Query Language is a read-only SQL subset that supports ad-hoc exploration in Docent.

Queries can only run over a single collection by design.

## Executing DQL via the Python SDK

```python
from docent.sdk.client import Docent

client = Docent()
collection_id = "<collection-uuid>"

# (Optional) inspect available tables/columns
schema = client.get_dql_schema(collection_id)

# Execute a DQL query
result = client.execute_dql(
    collection_id,
    "SELECT agent_runs.id AS agent_run_id FROM agent_runs LIMIT 10",
)

# Convert to dict rows (or use result['columns'] + result['rows'] directly)
rows = client.dql_result_to_dicts(result)
```

## Available Tables and Columns

| Table | Description |
| --- | --- |
| `agent_runs` | Information about each agent run in a collection. |
| `transcripts` | Individual transcripts tied to an agent run; stores serialized messages and per-transcript metadata. |
| `transcript_groups` | Hierarchical groupings of transcripts for runs. |
| `judge_results` | Scored rubric outputs keyed by agent run and rubric version. |
| `results` | Individual LLM analysis results from result sets. |

### `agent_runs`

| Column | Description |
| --- | --- |
| `id` | Agent run identifier (UUID). |
| `collection_id` | Collection that owns the run |
| `name` | Optional user-provided display name. |
| `description` | Optional description supplied at ingest time. |
| `metadata_json` | User supplied metadata, stored as JSON. |
| `created_at` | When the run was recorded in Docent. |

### `transcripts`

| Column | Description |
| --- | --- |
| `id` | Transcript identifier (UUID). |
| `collection_id` | Collection that owns the transcript. |
| `agent_run_id` | Parent run identifier; joins back to `agent_runs.id`. |
| `name` | Optional transcript title. |
| `description` | Optional description. |
| `transcript_group_id` | Optional grouping identifier. |
| `messages` | Binary-encoded JSON payload of message turns. |
| `metadata_json` | Binary-encoded metadata describing the transcript. |
| `created_at` | Timestamp recorded during ingest. |

### `transcript_groups`

| Column | Description |
| --- | --- |
| `id` | Transcript group identifier. |
| `collection_id` | Collection that owns the transcript. |
| `agent_run_id` | Parent run identifier; joins back to `agent_runs.id`. |
| `name` | Optional name for the group. |
| `description` | Optional descriptive text. |
| `parent_transcript_group_id` | Identifier of the parent group (for hierarchical groupings). |
| `metadata_json` | JSONB metadata payload for the group. |
| `created_at` | Timestamp recorded during ingest. |

### `judge_results`

| Column | Description |
| --- | --- |
| `id` | Judge result identifier. |
| `agent_run_id` | Run scored by the rubric. |
| `rubric_id` | Rubric identifier. |
| `rubric_version` | Version of the rubric used when scoring. |
| `output` | JSON representation of rubric outputs. |
| `result_metadata` | Optional JSON metadata attached to the result. |
| `result_type` | Enum describing the rubric output type. |

### `results`

| Column | Description |
| --- | --- |
| `id` | Result identifier (UUID). |
| `result_set_id` | Parent result set identifier; joins back to `result_sets.id`. |
| `llm_context_spec` | JSON specification describing the LLM context used. |
| `prompt_segments` | The user prompt sent to the LLM. |
| `user_metadata` | Optional JSON metadata supplied by the user. |
| `output` | JSON output from the LLM (for string schemas: `{"output": str, "citations": [...]}`). |
| `error_json` | JSON error details if the LLM call failed. |
| `input_tokens` | Number of input tokens consumed. |
| `output_tokens` | Number of output tokens generated. |
| `model` | Model identifier used for the request. |
| `created_at` | Timestamp when the result was created. |

## JSON Metadata Access Patterns

Docent stores user-supplied metadata as JSON. Access using Postgres operators:

```sql
-- Filter agent runs by a metadata attribute
SELECT id, name
FROM agent_runs
WHERE metadata_json->>'environment' = 'staging';
```

```sql
-- Retrieve nested transcript metadata
SELECT
  id,
  metadata_json->'conversation'->>'speaker' AS speaker,
  metadata_json->'conversation'->>'topic' AS topic
FROM transcripts
WHERE metadata_json->>'status' = 'flagged';
```

```sql
-- Cast numeric metadata for aggregation
SELECT
  AVG(CAST(metadata_json->>'latency_ms' AS DOUBLE PRECISION)) AS avg_latency_ms
FROM agent_runs
WHERE metadata_json ? 'latency_ms';
```

When querying JSON fields, comparisons default to string semantics. Cast values when you need numeric ordering or aggregation.

## Allowed Syntax

| Feature |
| --- |
| `SELECT`, `DISTINCT`, `FROM`, `WHERE`, subqueries |
| `JOIN`, `LEFT JOIN`, `RIGHT JOIN`, `FULL JOIN`, `CROSS JOIN` |
| `WITH` (CTEs) |
| `UNION [ALL]`, `INTERSECT`, `EXCEPT` |
| `GROUP BY`, `HAVING` |
| Aggregations (`COUNT`, `AVG`, `MIN`, `MAX`, `SUM`, `STDDEV_POP`, `STDDEV_SAMP`, `VAR_POP`, `VAR_SAMP`, `ARRAY_AGG`, `STRING_AGG`, `JSON_AGG`, `JSONB_AGG`, `JSON_OBJECT_AGG`, `PERCENTILE_CONT`, `PERCENTILE_DISC` with `WITHIN GROUP`) |
| Window functions (`ROW_NUMBER`, `RANK`, `DENSE_RANK`, `NTILE`, `LAG`, `LEAD`, `FIRST_VALUE`, `LAST_VALUE`, `NTH_VALUE`, `PERCENT_RANK`, `CUME_DIST`) |
| `ORDER BY`, `LIMIT`, `OFFSET` |
| Conditional & null helpers (`CASE`, `COALESCE`, `NULLIF`) |
| Boolean logic (`AND`, `OR`, `NOT`) |
| Comparison operators (`=`, `!=`, `<`, `<=`, `>`, `>=`, `IS`, `IS NOT`, `IS DISTINCT FROM`, `IN`, `BETWEEN`, `LIKE`, `ILIKE`, `EXISTS`, `SIMILAR TO`, `~`, `~*`, `!~`, `!~*`) |
| Arithmetic & math (`+`, `-`, `*`, `/`, `%`, `POWER`, `ABS`, `SIGN`, `SQRT`, `LN`, `LOG`, `EXP`, `GREATEST`, `LEAST`, `FLOOR`, `CEIL`, `ROUND`, `RANDOM`) |
| String helpers (`SUBSTRING`, `LEFT`, `RIGHT`, `LENGTH`, `UPPER`, `LOWER`, `INITCAP`, `TRIM`, `REPLACE`, `SPLIT_PART`, `POSITION`, `CONCAT`, `CONCAT_WS`, `STRING_AGG`) |
| JSON operators & functions (`->`, `->>`, `#>`, `#>>`, `@>`, `?`, `?|`, `?&`, `jsonb_build_object`, `jsonb_build_array`, `json_agg`, `jsonb_agg`, `json_object_agg`, `jsonb_set`, `jsonb_path_query`, `jsonb_path_exists`) |
| Date/time basics (`CURRENT_DATE`, `CURRENT_TIME`, `CURRENT_TIMESTAMP`, `NOW()`, `EXTRACT`, `DATE_TRUNC`, `AGE`, `AT TIME ZONE`, `timezone()`) |
| Interval arithmetic (`timestamp +/- INTERVAL`, `INTERVAL` literals, `MAKE_INTERVAL`, `JUSTIFY_DAYS`, `JUSTIFY_HOURS`, `JUSTIFY_INTERVAL`) |
| Construction & conversion (`MAKE_DATE`, `MAKE_TIME`, `MAKE_TIMESTAMP`, `MAKE_TIMESTAMPTZ`, `TO_CHAR`, `TO_DATE`, `TO_TIMESTAMP`, `DATE_PART`) |
| Array helpers (`ARRAY[...]`, `array_cat`, `array_length`, `cardinality`, `unnest`, `ARRAY(SELECT ...)`, `= ANY`, `= ALL`, `array_position`, `array_remove`) |
| Type helpers (`CAST`, `::`) |

Unsupported constructs include `*`, user-defined functions, and any DDL or DML commands.

## Example Queries

### Recent Runs

```sql
SELECT
  id,
  name,
  metadata_json->'model'->>'name' AS model_name,
  created_at
FROM agent_runs
WHERE metadata_json->>'status' = 'completed'
ORDER BY created_at DESC
LIMIT 10;
```

### Transcript Counts per Group

```sql
SELECT
  tg.id AS group_id,
  tg.name AS group_name,
  COUNT(t.id) AS transcript_count
FROM transcript_groups tg
JOIN transcripts t ON t.transcript_group_id = tg.id
GROUP BY tg.id, tg.name
HAVING COUNT(t.id) > 1
ORDER BY transcript_count DESC;
```

### Flagged Judge Results

```sql
SELECT
  jr.agent_run_id,
  jr.rubric_id,
  jr.result_metadata->>'label' AS label,
  jr.output->>'score' AS score
FROM judge_results jr
WHERE jr.result_metadata->>'severity' = 'high'
  AND EXISTS (
    SELECT 1
    FROM agent_runs ar
    WHERE ar.id = jr.agent_run_id
      AND ar.metadata_json->>'environment' = 'prod'
  )
ORDER BY score DESC
LIMIT 25;
```

### Completion Rate by Environment

```sql
WITH normalized_runs AS (
  SELECT
    metadata_json->>'environment' AS environment,
    metadata_json->>'status' AS status
  FROM agent_runs
  WHERE metadata_json ? 'environment'
)
SELECT
  environment,
  COUNT(environment) AS total_runs,
  SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_runs,
  CAST(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS DOUBLE PRECISION)
    / NULLIF(COUNT(environment), 0) AS completion_rate
FROM normalized_runs
GROUP BY environment
ORDER BY total_runs DESC;
```

### Latest Rubric Scores by Model

```sql
WITH latest_scores AS (
  SELECT
    agent_run_id,
    MAX(rubric_version) AS rubric_version
  FROM judge_results
  WHERE rubric_id = 'helpful_response_v1'
  GROUP BY agent_run_id
)
SELECT
  ar.id,
  ar.metadata_json->'model'->>'name' AS model_name,
  jr.output->>'score' AS score,
  jr.result_metadata->>'label' AS label
FROM latest_scores ls
JOIN judge_results jr
  ON jr.agent_run_id = ls.agent_run_id
  AND jr.rubric_version = ls.rubric_version
  AND jr.rubric_id = 'helpful_response_v1'
JOIN agent_runs ar ON ar.id = jr.agent_run_id
WHERE ar.metadata_json->>'environment' = 'prod'
ORDER BY CAST(jr.output->>'score' AS DOUBLE PRECISION) DESC
LIMIT 15;
```

## Restrictions and Best Practices

- **Read-only**: Only `SELECT`-style queries are permitted.
- **Single statement**: Batches or multiple statements are rejected.
- **Explicit projection**: Wildcard projections (`*`) are disallowed. List the columns you need.
- **Collection scoping**: A single query can only access data within a single collection.
- **Limit enforcement**: Every query is capped at 10,000 rows. Use pagination (`OFFSET`/`LIMIT`) for larger result sets.
- **JSON performance**: Heavy JSON traversal across large collections can be slow. Prefer top-level fields when available.
- **Type awareness**: Cast values explicitly when precision matters.

## Reminders and tips for using DQL

### No Wildcards Allowed
- `SELECT *` is forbidden
- `COUNT(*)` is forbidden - use `COUNT(column_name)` instead

### GROUP BY Alias Workaround
Aliases don't work directly in GROUP BY when selecting from `agent_runs`. Use a subquery:

```sql
SELECT task, model_name, COUNT(task) AS run_count
FROM (
    SELECT
        metadata_json->>'task' AS task,
        metadata_json->'agent'->>'model_name' AS model_name
    FROM agent_runs
    WHERE ...
) AS subq
GROUP BY task, model_name
```

### Avoid Dynamic IN Clauses with String Interpolation
Building IN clauses with f-strings is dangerous:
- Task names containing `::` can be parsed as PostgreSQL type casts
- Instead: fetch all relevant data and filter in Python with `.isin()`

### JSON Access Patterns
- Nested: `metadata_json->'parent'->>'child'`
- Flat key with dot: `metadata_json->>'parent.child'`
- Check key existence: `metadata_json ? 'key'`
