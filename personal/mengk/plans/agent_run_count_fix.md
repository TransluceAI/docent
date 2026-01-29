# Plan: Replace per‑ingest `count(*)` with cached agent run counts

## 1. Request understanding
The ingest worker `docent_core/docent/workers/agent_run_ingest_worker.py` is triggering repeated `SELECT count(*) FROM agent_runs WHERE collection_id = $1` queries, which are showing up as slow in Postgres logs (examples in the user report for 2026‑01‑29). The goal is to stop running this full count on every ingest job while preserving the 1,000,000 agent run limit and not breaking existing ingest paths.

### Ambiguities / questions to confirm
1. **Strict vs soft limit**: The worker comment currently says “soft limit allows slight overages in race conditions.” Is that still acceptable if we move to a cached counter? (I assume **yes**, but confirmation helps determine whether we need an atomic “reserve” update.)
2. **Backfill strategy**: Can we run a one‑time backfill query on production (counts by collection), or do you prefer **lazy backfill on first use** to avoid a heavy migration?
3. **API counts**: Should `/collections` and `/collection_details` switch to the cached count for speed, or keep exact `count(*)` there (slower but “ground truth”)?
4. **Telemetry ingest**: Telemetry upserts runs outside `add_agent_runs`. Are you OK with updating the cached count in that path too? (Needed for correctness.)

## 2. Codebase exploration (current behavior)

### Ingest worker triggers count per job
`docent_core/docent/workers/agent_run_ingest_worker.py`:
```python
# Check space and add runs (no lock - soft limit allows slight overages in race conditions)
await mono_svc.check_space_for_runs(ctx, len(runs_request.agent_runs))
await mono_svc.add_agent_runs(ctx, runs_request.agent_runs)
```
This calls `check_space_for_runs` for **every ingest job**.

### `check_space_for_runs` does a full count
`docent_core/docent/services/monoservice.py`:
```python
async def count_collection_agent_runs(self, collection_id: str) -> int:
    async with self.db.session() as session:
        query = select(func.count()).where(SQLAAgentRun.collection_id == collection_id)
        result = await session.execute(query)
        return result.scalar_one()

async def check_space_for_runs(self, ctx: ViewContext, new_runs: int):
    existing_runs = await self.count_collection_agent_runs(ctx.collection_id)
    agent_run_limit = 1_000_000
    if existing_runs + new_runs > agent_run_limit:
        raise ValueError(...)
```
This is the exact `count(*)` shown in the DB log snippet.

### Inserts that should update a cached count
`docent_core/docent/services/monoservice.py` inserts agent runs and related rows:
```python
async def add_agent_runs(self, ctx: ViewContext, agent_runs: Sequence[AgentRun]):
    ...
    async with self.db.session() as session:
        session.add_all(agent_run_data)
        session.add_all(transcript_group_data)
        await session.flush()
        session.add_all(transcript_data)
```
This is the best place to update a per‑collection counter in the same transaction.

### Other paths that create/delete agent runs
- Telemetry upsert path (also calls `check_space_for_runs`):
  `docent_core/docent/services/telemetry.py` `update_agent_runs_for_telemetry` computes `new_agent_run_count` (new IDs vs existing) and then merges agent runs. This path must also update the cached count.
- Deletions:
  `docent_core/docent/services/monoservice.py` `delete_agent_runs` deletes agent runs and returns `deleted_count`; we must decrement the cached count here.
- Clone uses `add_agent_runs`, so it will be covered if `add_agent_runs` updates count.

### Schema context
`docent_core/docent/db/schemas/tables.py`:
- `SQLACollection` currently has no count column.
- `SQLAAgentRun.collection_id` is indexed and used in the count query.

## 3. Possible approaches

### Approach A (recommended): cached counter on `collections`
Add `collections.agent_run_count` and keep it updated on insert/delete/upsert. `check_space_for_runs` reads this value instead of doing `count(*)`.
- **Pros**: Eliminates hot `count(*)` queries; minimal DB impact per ingest; easy to read count for APIs.
- **Cons**: Must ensure all insert/delete paths keep it in sync; needs backfill.

### Approach B: DB trigger + stats table
Create a `collection_stats` table with a trigger on `agent_runs` insert/delete to maintain counts.
- **Pros**: DB‑level correctness; app code simpler.
- **Cons**: New triggers/functions; operationally heavier; no existing trigger pattern in repo.

### Approach C: approximate counts (pg_class.reltuples)
Use Postgres table stats for approximate counts.
- **Pros**: No schema changes.
- **Cons**: Not accurate enough for enforcing limits; counts drift between ANALYZE runs.

### Approach D: sharded counters (avoid hot row)
Maintain multiple counter rows per collection (e.g., `collection_id + shard_id`), update one shard per ingest job, and sum on read.
- **Pros**: Reduces contention on a single collection row under heavy concurrent ingest.
- **Cons**: More complex schema + read path; strict limit enforcement becomes harder (needs a sum + lock).

## 4. Recommended approach
Use **Approach A** (cached `agent_run_count` on `collections`) with a **one‑time backfill** or **lazy initialization** fallback, then update it in all insert/delete/upsert paths.

## 5. Implementation plan (detailed)

### Step 1: Add `agent_run_count` to `collections`
- File: `docent_core/docent/db/schemas/tables.py`
- Add a column to `SQLACollection`:
  ```python
  agent_run_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
  ```
  Rationale: allow `NULL` for “unknown” so we can lazy‑backfill on first access. If you prefer eager backfill, set `nullable=False, default=0` instead.

### Step 2: Alembic migration
- Create a new Alembic revision (similar style to `alembic/versions/5c581f3bd108_add_is_clone_to_collections.py`).
- Migration should:
  1. Add the `agent_run_count` column (nullable at first if doing lazy backfill).
  2. **Optional backfill** in the migration or as a separate script.

**Backfill option A (in migration):**
```sql
UPDATE collections c
SET agent_run_count = sub.cnt
FROM (
  SELECT collection_id, COUNT(*) AS cnt
  FROM agent_runs
  GROUP BY collection_id
) sub
WHERE c.id = sub.collection_id;

UPDATE collections SET agent_run_count = 0 WHERE agent_run_count IS NULL;
```
If the `agent_runs` table is huge, run this during a maintenance window.

**Backfill option B (lazy):**
Skip the data update in migration; let the first `check_space_for_runs` call compute and store the count for that collection.

### Step 3: Replace `count(*)` in `check_space_for_runs`
- File: `docent_core/docent/services/monoservice.py`
- Change `check_space_for_runs` to:
  1. Read `SQLACollection.agent_run_count` for `ctx.collection_id`.
  2. If `NULL`, compute `count(*)` **once**, store it in `collections.agent_run_count`, and use that value.
  3. Compare `existing + new_runs` to the limit.

Example logic (pseudocode):
```python
async with self.db.session() as session:
    result = await session.execute(
        select(SQLACollection.agent_run_count).where(SQLACollection.id == ctx.collection_id)
    )
    existing = result.scalar_one_or_none()
    if existing is None:
        count_result = await session.execute(
            select(func.count()).where(SQLAAgentRun.collection_id == ctx.collection_id)
        )
        existing = int(count_result.scalar_one() or 0)
        await session.execute(
            update(SQLACollection)
            .where(SQLACollection.id == ctx.collection_id)
            .values(agent_run_count=existing)
        )

if existing + new_runs > agent_run_limit:
    raise ValueError(...)
```
This reduces `count(*)` to **at most once per collection**.

### Step 4: Update count on insert paths

#### 4a. `MonoService.add_agent_runs`
- File: `docent_core/docent/services/monoservice.py`
- After adding agent runs (within the same session), increment the collection’s count:
  ```python
  if agent_runs:
      await session.execute(
          update(SQLACollection)
          .where(SQLACollection.id == ctx.collection_id)
          .values(agent_run_count=SQLACollection.agent_run_count + len(agent_runs))
      )
  ```
- This should be in the same `async with self.db.session()` block so the count update rolls back if insert fails.

#### 4b. Telemetry upsert path
- File: `docent_core/docent/services/telemetry.py` `update_agent_runs_for_telemetry`
- The function already computes `new_agent_run_count`.
- After successful merges/inserts (before commit), increment `SQLACollection.agent_run_count` by `new_agent_run_count` when `new_agent_run_count > 0`.
  Use `self.session.execute(update(...))` to keep it in the same transaction.

### Step 5: Update count on delete
- File: `docent_core/docent/services/monoservice.py` `delete_agent_runs`
- After deletion, decrement `agent_run_count` by `deleted_count` (in the same session):
  ```python
  if deleted_count:
      await session.execute(
          update(SQLACollection)
          .where(SQLACollection.id == collection_id)
          .values(agent_run_count=SQLACollection.agent_run_count - deleted_count)
      )
  ```

### Step 6 (optional but recommended): Use cached count in collection APIs
Currently `/collections` and `/collection_details` call `batch_count_collection_agent_runs`, which still runs `count(*)` queries.
- Update `batch_count_collection_agent_runs` to read from `SQLACollection.agent_run_count` (and fallback to `0` if `NULL`).
- This avoids additional count scans when listing collections.

### Step 7: Tests / validation
- Add or update tests to ensure counts stay correct:
  - `tests/integration/test_clone_collection.py` already expects `agent_run_count` to reflect inserted runs; verify it still passes.
  - Add a unit/integration test for `delete_agent_runs` that asserts the count decrements.
  - Add a telemetry test (if available) to assert `new_agent_run_count` increments the cached count.

### Step 8: Observability
- Add a log once when `agent_run_count` is lazy‑backfilled (if using lazy path), to make it visible that the fallback count ran.
- Confirm via Postgres logs/pg_stat_statements that the `count(*)` query no longer shows up during ingest.

## 6. Risks / edge cases
- **Count drift** if there are any insert/delete paths not covered (search for any direct writes to `agent_runs`). I did not find other direct writes besides `add_agent_runs` and telemetry merge.
- **Negative counts** if deletions exceed count due to mismatch; clamp to zero if desired.
- **Race conditions**: The current limit check is already “soft”. The cached count approach preserves that behavior unless we add an atomic reservation update.
- **Hot row contention**: A single `collections` row per collection becomes a contention point if many jobs ingest into the same collection concurrently. The lock is row‑level and held only for the duration of the `UPDATE`, which is typically much cheaper than repeated `count(*)` scans. If contention is still high, consider sharded counters (Approach D).
- **Stale cached count**: If any path writes to `agent_runs` without updating the counter (or external SQL writes occur), the count can drift. Mitigations: ensure all known write paths update the counter, and optionally add a periodic reconciliation job or lazy recompute when `agent_run_count` is NULL/negative.


## 7. Optional stricter enforcement (if you want)
If you want **strict** limit enforcement without race conditions, we can replace `check_space_for_runs` with a single atomic update in the same transaction as inserts:
```sql
UPDATE collections
SET agent_run_count = agent_run_count + :new_runs
WHERE id = :collection_id
  AND agent_run_count + :new_runs <= :limit
RETURNING agent_run_count;
```
If no row is returned, reject the ingest. This requires moving the check into the same session/transaction as inserts (e.g., inside `add_agent_runs`) so a rollback restores the count if inserts fail.

## 8. Summary of files to change
- `docent_core/docent/db/schemas/tables.py` (add `agent_run_count` column)
- `alembic/versions/<new_revision>_add_agent_run_count_to_collections.py` (migration + optional backfill)
- `docent_core/docent/services/monoservice.py` (update `check_space_for_runs`, `add_agent_runs`, `delete_agent_runs`, optionally `batch_count_collection_agent_runs`)
- `docent_core/docent/services/telemetry.py` (update `update_agent_runs_for_telemetry` to increment count)
- Tests as needed (likely `tests/integration/test_clone_collection.py` plus new delete test)
