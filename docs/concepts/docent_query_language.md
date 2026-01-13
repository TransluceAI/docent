# Docent Query Language (DQL)

Docent Query Language is a read-only SQL subset that supports ad-hoc exploration in Docent.

Queries can only run over a single collection by design (if you need multi-collection support, please reach out to us!)

## Available Tables and Columns

| Table | Description |
| --- | --- |
| `agent_runs` | Information about each agent run in a collection. |
| `transcripts` | Individual transcripts tied to an agent run; stores serialized messages and per-transcript metadata. |
| `transcript_groups` | Hierarchical groupings of transcripts for runs. |
| `judge_results` | Scored rubric outputs keyed by agent run and rubric version. |

### `agent_runs`

| Column | Description |
| --- | --- |
| `id` | Agent run identifier (UUID). |
| `collection_id` | Collection that owns the run |
| `name` | Optional user-provided display name. |
| `description` | Optional description supplied at ingest time. |
| `metadata_json` | User suplied metadata, stored as JSON.  |
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

### JSON Metadata Paths

Docent stores user-supplied metadata as JSON, and can be access in Postgres style. Here are some examples:

#### Access Patterns
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

DQL supported keywords:

| Feature |
| --- |
| `SELECT`, `DISTINCT`, `FROM`, `WHERE`, subqueries |
| `JOIN`, `LEFT JOIN`, `RIGHT JOIN`, `FULL JOIN`, `CROSS JOIN` |
| `WITH` (CTEs) |
| `UNION [ALL]`, `INTERSECT`, `EXCEPT` |
| `GROUP BY`, `HAVING` |
| Aggregations (`COUNT`, `AVG`, `MIN`, `MAX`, `SUM`, `STDDEV_POP`, `STDDEV_SAMP`, `VAR_POP`, `VAR_SAMP`, `ARRAY_AGG`, `STRING_AGG`, `JSON_AGG`, `JSONB_AGG`, `JSON_OBJECT_AGG`, `PERCENTILE_CONT`, `PERCENTILE_DISC` (`WITHIN GROUP`)) |
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

## Examples

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

Aggregates per-environment success rates by normalizing metadata into a CTE.

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
  COUNT(*) AS total_runs,
  SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_runs,
  CAST(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS DOUBLE PRECISION)
    / NULLIF(COUNT(*), 0) AS completion_rate
FROM normalized_runs
GROUP BY environment
ORDER BY total_runs DESC;
```

### Latest Rubric Scores by Model

Pulls the most recent rubric result per run, then joins runs to surface the model responsible for the score.

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

### Transcript Coverage Audit

Finds transcript groups that are marked as `must_have` but have no associated transcripts.

```sql
SELECT
  tg.id AS group_id,
  tg.name AS group_name,
  COUNT(t.id) AS transcript_count
FROM transcript_groups tg
LEFT JOIN transcripts t
  ON t.transcript_group_id = tg.id
  AND t.collection_id = tg.collection_id
WHERE tg.metadata_json->>'priority' = 'must_have'
GROUP BY tg.id, tg.name
HAVING COUNT(t.id) = 0
ORDER BY group_name;
```

## Restrictions and Best Practices

- **Read-only**: Only `SELECT`-style queries are permitted. Use bulk exports or ingestion utilities to modify data outside of DQL.
- **Single statement**: Batches or multiple statements are rejected to avoid mixed workloads.
- **Explicit projection**: Wildcard projections (`*`) are disallowed. List the columns you need so downstream tooling (schema builders, type generation) stays predictable.
- **Collection scoping**: A single query can only access data within a single collection.
- **Limit enforcement**: Every query is capped at 10,000 rows by the server. If you omit `LIMIT` or request more, Docent automatically applies the cap—use pagination (`OFFSET`/`LIMIT`) or offline exports for larger result sets.
- **JSON performance**: Metadata fields are stored as JSON; heavy traversal across large collections can be slower than filtering on indexed scalar columns. Prefer top-level fields when available.
- **Type awareness**: The registry tracks datatypes for JSON metadata paths. When a path supports multiple types Docent may fall back to string comparisons, so cast where precision matters (e.g., `CAST(metadata_json->>'duration_ms' AS BIGINT)`).
