# Agent Run Ingestion Slowdown Report and Fix Plan

## Context
- Incident: AgentRun ingestion is extremely slow for a collection with ~880,000 existing AgentRuns.
- Hot path: `docent_core/docent/workers/agent_run_ingest_worker.py` -> `MonoService.check_space_for_runs` -> `MonoService.add_agent_runs` in `docent_core/docent/services/monoservice.py`.
- DB schema: `SQLAAgentRun` and related tables in `docent_core/docent/db/schemas/tables.py`.

## Findings (from code inspection)
1. **Full count on every ingest job**
   - `check_space_for_runs` calls `count_collection_agent_runs`, which executes `SELECT count(*) FROM agent_runs WHERE collection_id = :id`.
   - This runs on every ingest job and is wrapped inside an advisory lock, so it serializes and can require scanning ~880k rows each time.

2. **ORM-heavy inserts for large batches**
   - `add_agent_runs` builds ORM objects for every run, transcript, and transcript group, then `session.add_all(...)` and `session.flush()`.
   - This is CPU-heavy in Python, grows the SQLAlchemy identity map, and can issue many single-row inserts. It gets slower as payload size grows.

3. **GIN index maintenance on `metadata_json`**
   - `SQLAAgentRun` has a GIN index on `metadata_json`. Inserts into a large GIN index can be expensive and get slower as the table grows.

4. **Advisory lock serializes ingestion**
   - `agent_run_ingest_job` wraps `check_space_for_runs` + `add_agent_runs` in `advisory_lock(collection_id, action_id="mutation")`.
   - Any slowness in count or insert directly reduces throughput because only one job proceeds per collection at a time.

## Hypothesis
The main slowdown is likely the combination of:
- Full-table (collection-scoped) counts per job under a per-collection lock.
- ORM insert overhead with large payloads.
- GIN index update cost on `metadata_json`.

## Diagnostics to run (confirm before changing behavior)
1. **Time each step**
   - Add timing logs around: payload fetch, decode, Pydantic validation, `check_space_for_runs`, `add_agent_runs`, and commit.
2. **DB-level evidence**
   - `EXPLAIN ANALYZE` for the count query with the affected collection id.
   - Check `pg_stat_statements` for the slowest queries during ingestion.
   - Check `pg_locks` for advisory lock contention and wait times.
3. **Payload profiling**
   - Log number of runs, transcripts, transcript groups, and payload size per job.

## Fix Plan

### Phase 1: Reduce per-job count cost
1. **Introduce a cached count**
   - Add `agent_run_count` to the collection row (or a new per-collection stats table).
   - Backfill counts once for existing collections.
   - Replace `count_collection_agent_runs` with an atomic `UPDATE ... SET agent_run_count = agent_run_count + :new_runs` and check against the limit in the same transaction.
2. **Locking change**
   - Replace advisory lock with a row-level lock on the collection row during the count update, or keep advisory lock but reduce its scope to only the count update.

### Phase 2: Speed up inserts
1. **Bulk inserts**
   - Replace `session.add_all(...)` with `session.execute(insert(table), rows)` for agent runs, transcript groups, and transcripts.
   - Insert in batches (size-based) to reduce memory pressure and avoid very large single transactions.
2. **Order of operations**
   - Insert agent runs and transcript groups first, then transcripts, to satisfy FK constraints without `session.flush()` overhead.

### Phase 3: Index and DB tuning
1. **GIN index strategy**
   - Evaluate whether the GIN index on `metadata_json` is required for the ingest-heavy path.
   - If required, consider adjusting `gin_pending_list_limit` and `fastupdate` to reduce insertion cost.
2. **Maintenance**
   - Ensure `ANALYZE` and `VACUUM` are healthy for `agent_runs` and related tables to keep planner stats current.

### Phase 4: Concurrency improvements
1. **Parallel ingestion**
   - After count tracking is no longer a full scan, allow multiple ingest jobs per collection to run concurrently (bounded by worker concurrency).
2. **Backpressure**
   - Cap batch sizes or job payload sizes to keep ingest latency predictable and avoid giant transactions.

## Validation
- Load test with a collection at ~900k runs.
- Compare ingest throughput and job latency before/after.
- Verify the 1,000,000 run limit is enforced correctly with the new counter.

## Suggested Immediate Mitigation (if incident is active)
- Temporarily disable the count check for trusted internal ingest to restore throughput.
- Reduce batch size for ingestion to decrease lock hold time and transaction size.
