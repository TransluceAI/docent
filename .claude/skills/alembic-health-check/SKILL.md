---
name: alembic-health-check
description: Diagnose Alembic migration state and upgrade readiness with static, non-mutating analysis in Python projects.
---

# Alembic Health Check

Run a deterministic Alembic health check, collect evidence, and return a clear diagnosis with next actions.

## Workflow

1. Identify the Alembic command context.
   - Run from the repository root unless project docs specify another directory.
   - Detect config entrypoint (`alembic.ini` or custom config) and use `alembic -c <path>` when needed.
   - Ensure required DB environment variables are loaded.

2. Collect baseline migration state before changing anything.
   - `alembic current -v`
   - `alembic heads -v`
   - `alembic branches -v`
   - `alembic history --verbose`
   - Optional consistency check: `alembic check`
   - Optional focused graph slice: `alembic history -r-20:current`

3. Assess upgrade feasibility without running migrations.
   - Compare `current` vs `heads` to estimate pending revision count.
   - Use `history` and `branches` output to verify a valid path from current revision(s) to head.
   - Flag uncertainty when static checks cannot prove runtime success (data migrations, raw SQL, env-dependent logic).
   - Classify status as `likely-safe`, `blocked`, or `uncertain`.

4. Diagnose and classify findings.
   - Healthy: one head, current revision equals head, no branch anomalies.
   - Multiple heads: `alembic heads` returns more than one revision.
   - Missing revision: errors like `Can't locate revision identified by ...`.
   - Diverged DB/code: `current` revision is unknown in local history or not on the expected path to head.
   - Config/environment failure: cannot load script location, metadata imports, or DB settings.
   - Upgrade risk (static): graph looks valid but runtime may still fail due to migration code behavior.
