# Task Plan: Multi-Transcript Actions Summary

## Goal
Implement one-click actions summary analysis across every transcript in an AgentRun, then switch Docent's LLM routing to DeepSeek-only flash/pro models.

## Phases
- [x] Phase 1: Load project instructions and inspect current summary flow
- [x] Phase 2: Implement backend multi-transcript summary streaming
- [x] Phase 3: Update frontend types, store, and summary UI
- [x] Phase 4: Add focused tests
- [x] Phase 5: Switch LLM provider preferences to DeepSeek-only
- [x] Phase 6: Run verification and report exact state

## Key Decisions
- Keep `/actions_summary` and SSE transport unchanged.
- Process transcripts sequentially in v1 to avoid unbounded LLM fanout.
- Add `transcript_summaries` and keep legacy `low_level`, `high_level`, and `observations` as the first transcript's result.
- Pass the real `transcript_idx` into summarizer transcript rendering so citations navigate to the correct transcript.
- Render per-transcript results in `AgentSummary`; leave `AgentRunViewer` navigation logic unchanged.
- DeepSeek provider uses the official OpenAI-compatible base URL `https://api.deepseek.com`.
- Model strength mapping: low-cost/fast summary and mini/flash assignment paths use `deepseek-v4-flash`; stronger chat, judge, search, refinement, and synthesis paths use `deepseek-v4-pro`.

## Errors Encountered
- `uv run pytest tests/unit/test_actions_summary.py -q` failed before collection because pytest was not installed in the default environment; retry with `uv run --extra dev pytest ...`.
- `uv run --extra dev pytest ...` initially failed before collection because `.env` did not exist; created ignored local `.env` from template with blank `DEEPSEEK_API_KEY`.
- `bun run lint` initially could not run because `bun` was not installed and `node_modules` was absent.
- `uv.lock` was rewritten by `uv run --extra dev` to a local mirror registry; restored it to HEAD because it was unrelated.
- `bun install --frozen-lockfile` failed because `bun.lock` was stale relative to `package.json`; `bun install` refreshed the lockfile.
- `next lint` is no longer a valid command in the installed Next.js CLI; changed the `lint` script to direct ESLint CLI.
- `next build` required Next 16 dynamic route typing updates and `NEXT_PUBLIC_API_HOST` during local build.

## Status
**Complete** - backend, frontend, DeepSeek provider routing, focused tests, and frontend lint/build verification are implemented.

---

# Task Plan: LLM Provider Docker Configuration

## Goal
Add a self-hosting configuration interface that lets users choose the default LLM provider and models without editing Python code.

## Phases
- [x] Phase 1: Inspect current provider preferences, Docker env flow, and self-hosting docs
- [x] Phase 2: Add env-driven provider/model selection with DeepSeek defaults
- [x] Phase 3: Wire Docker Compose and docs to the new configuration
- [x] Phase 4: Add/update tests and run focused verification

## Decisions Made
- Keep `deepseek` as the default provider.
- Add `DOCENT_LLM_PROVIDER` as the simple provider selector.
- Add optional `DOCENT_LLM_FLASH_MODEL` and `DOCENT_LLM_PRO_MODEL` for switching to any registered provider without code edits.
- Do not restore old OpenAI/Anthropic/Google default fallback lists; non-DeepSeek providers must be explicit.
- Add `DOCENT_LLM_BASE_URL` and `DOCENT_LLM_API_KEY` so self-host users can point Docent at DeepSeek or any custom OpenAI-compatible endpoint.
- Add per-feature model env vars for chat, judge, summaries, observations, search, refinement, and clustering.

## Errors Encountered
- Pyright did not narrow env-derived reasoning effort strings to Literal types; fixed with an explicit cast after validation.
- `uv run --extra dev` rewrote `uv.lock` registry URLs to a local mirror again; restored `uv.lock` to HEAD because the lockfile change was unrelated.

## Status
**Complete** - self-host LLM provider/base-url/key/per-feature model configuration is implemented, documented, and verified.

---

# Task Plan: Docent-Native Hodoscope Analysis Layer

## Goal
Implement a click-triggered Hodoscope analysis layer in local Docent with JSONB artifact storage, a background worker, REST APIs, and a native behavior map.

## Phases
- [x] Phase 1: Add dependency, schema, migration, and worker registration
- [x] Phase 2: Implement Docent-owned Hodoscope extraction, summarization, embedding, projection, storage, and APIs
- [x] Phase 3: Add frontend RTK API, dashboard panel, map, artifact download, and run/cancel controls
- [x] Phase 4: Add focused tests and run verification
- [x] Phase 5: Final status check and report exact changed files

## Key Decisions
- Pin upstream `hodoscope` from GitHub commit `e9b6930d4a0149cf76b15190a85dc9d9ff78a860`.
- Do not call Hodoscope CLI, LiteLLM summarization, or LiteLLM embedding paths.
- Use Docent `Transcript.units_of_action` for action extraction so points can deep-link back to transcript/block positions.
- Store artifacts and projection data in Postgres JSONB.
- Use Docent provider preferences for summaries and existing OpenAI embedding helper for 512-dimensional action embeddings.
- Keep the first version user-triggered only; no automatic analysis on dashboard load.

## Errors Encountered
- `uv run pytest -m integration -v tests/integration/test_hodoscope_analysis.py` could not reach the local test Postgres database because `docent_user` authentication failed for `_pytest_docent_test`; the test file itself was added and remains runnable once the local DB credentials match the test fixture.
- `uv run pre-commit run --all-files` formatted unrelated historical files; those hook-generated unrelated changes were reverted, then `pre-commit run --files ...` was used for the Hodoscope change set.
- `bun run build` needs `NEXT_PUBLIC_API_HOST`; reran successfully with `NEXT_PUBLIC_API_HOST=http://localhost:8889`.

## Status
**Complete** - Hodoscope dependency, JSONB storage, worker, REST APIs, native dashboard panel, tests, and focused verification are implemented.

---

# Task Plan: Live Hodoscope Validation With Agent-Test Trajectory

## Goal
Validate the current Hodoscope implementation against the real Agent-Test trajectory projection and local API keys without exposing secret values.

## Phases
- [x] Phase 1: Locate Agent-Test trajectory surface and key sources
- [x] Phase 2: Convert real trajectory projection data into Docent SDK AgentRuns
- [x] Phase 3: Run Hodoscope action extraction on real data
- [x] Phase 4: Run real LLM summary and tighten implementation if needed
- [x] Phase 5: Check embedding/full-job readiness and report blockers

## Key Decisions
- Treat `/data/lyuwt/Agent-test` as a case typo; use `/data/lyuwt/Agent-Test`.
- Use `/data/lyuwt/Agent-Test/docent_projection/dist/agent_runs.json` as the compact trajectory surface for the first live validation.
- Do not print API key values; only report variable names and whether required key classes are present.

## Errors Encountered
- Initial `/data/lyuwt/Agent-test` lookup failed because the real path is `/data/lyuwt/Agent-Test`.
- The projection data stores assistant `tool_calls` in OpenAI shape; the live test harness converts them to Docent SDK `ToolCall` shape before constructing `AgentRun`.
- A real DeepSeek summary call returned copied tool-call markup instead of a two-line action summary; the Hodoscope summary prompt needs to be tightened for tool-call-heavy trajectory text.
- Full embedding completion is blocked in the available Agent-Test/docent-inner key set because neither `.env` contains `OPENAI_API_KEY` or `OPENAI_ADMIN_KEY`; Hodoscope now fails before calling OpenAI with a clear RuntimeError.

## Status
**Complete** - real extraction and DeepSeek summary validation passed; full Hodoscope completion needs an OpenAI embedding key.

---

# Task Plan: OpenAI-Compatible Embedding Alignment

## Goal
Align Hodoscope embeddings with Docent's OpenAI-compatible LLM configuration so local embedding servers can be used without an OpenAI key.

## Phases
- [x] Phase 1: Inspect current OpenAI embedding helper and LLM-compatible env surface
- [x] Phase 2: Add embedding env/config resolution and client routing
- [x] Phase 3: Wire Hodoscope config to the resolved embedding model/dimensions
- [x] Phase 4: Add tests and run focused verification

## Key Decisions
- Prefer embedding-specific env vars when present.
- Fall back to `DOCENT_LLM_BASE_URL` and `DOCENT_LLM_API_KEY` when `DOCENT_LLM_PROVIDER=custom`.
- Keep OpenAI defaults for hosted OpenAI usage.
- Send text chunks, not token-id chunks, to the embeddings endpoint for better OpenAI-compatible local server support.
- Add Hodoscope-only embedding overrides so non-512 local models do not have to change Docent's fixed 512-dimensional transcript embedding table.

## Errors Encountered
- None in this pass.

## Status
**Complete** - Hodoscope embeddings now support OpenAI-compatible local embedding endpoints through env configuration, with focused unit and pre-commit verification.

---

# Task Plan: Local High-Quality Embedding Server

## Goal
Deploy a local OpenAI-compatible embedding server for Hodoscope using the strongest feasible embedding model on this workstation.

## Phases
- [x] Phase 1: Check GPU, disk, ports, existing Python/Docker runtime
- [x] Phase 2: Choose model and serving backend
- [x] Phase 3: Start local embedding server
- [x] Phase 4: Verify `/v1/embeddings` and Docent/Hodoscope env compatibility
- [x] Phase 5: Record restart command and limits

## Key Decisions
- Prefer Docker/vLLM over installing vLLM into Docent's Python 3.13 `.venv`.
- Use `/data/lyuwt/.cache/huggingface` for model cache to avoid filling `/home`.
- Supersede the first `Qwen/Qwen3-Embedding-8B` deployment with two smaller task-specific endpoints:
  - Docent global embeddings: `BAAI/bge-small-zh-v1.5`, native 512 dimensions, `http://localhost:8001/v1`.
  - Hodoscope embeddings: `Qwen/Qwen3-Embedding-0.6B`, native 1024 dimensions, `http://localhost:8000/v1`.
- Use `vllm/vllm-openai:v0.10.2`, not `latest`, because `latest` uses CUDA 13 / torch cu130 and the host driver exposes CUDA 12.8.
- Keep CUDA graph enabled in the final deployment; both final servers used vLLM default optimized mode with CUDA graph capture and Flash Attention.
- Hodoscope's Qwen endpoint keeps prefix caching and chunked prefill enabled; the Docent BGE endpoint uses CLS pooling, so vLLM disables prefix caching and chunked prefill for that model.

## Errors Encountered
- `docker pull vllm/vllm-openai:latest` failed because Docker daemon did not inherit the shell proxy; resolved by downloading image tar through `/data/lyuwt/tools/regctl` and `docker load`.
- `vllm/vllm-openai:latest` loaded but could not use CUDA because torch was `2.11.0+cu130` while the host driver reports CUDA 12.8; removed that image and switched to `v0.10.2`.
- Docker GPU runtime was configured but `nvidia-container-runtime` is not installed; resolved by manually passing `/dev/nvidia*` devices and host NVIDIA driver libraries into the container.
- The first container network mode made `127.0.0.1:1283` proxy point inside the container; resolved by using `--network host`.

## Status
**Complete** - local vLLM OpenAI-compatible embedding servers are running on `http://localhost:8001/v1` for Docent 512-dimensional embeddings and `http://localhost:8000/v1` for Hodoscope 1024-dimensional embeddings; both endpoints are smoke-tested.

---

# Task Plan: Agent-Test Import And Hodoscope Analysis

## Goal
Import the existing Agent-Test projected runs and raw trajectory references into the local `docent-inner` deployment, then run a Docent-native Hodoscope behavior analysis against that collection.

## Phases
- [x] Phase 1: Load communication, planning, Docent ingestion, and Docent analysis instructions
- [x] Phase 2: Inspect Agent-Test projection/traj source files and current worktree
- [x] Phase 3: Bring up or connect to a local Docent Postgres/Redis/server/worker without disturbing existing containers
- [x] Phase 4: Import 89 projected AgentRuns into a local collection
- [x] Phase 5: Run Hodoscope analysis with local Qwen3 embeddings and DeepSeek summaries
- [x] Phase 6: Verify counts, artifact/projection availability, and report usable links/paths

## Key Decisions
- Use `/data/lyuwt/Agent-Test/docent_projection/dist/agent_runs.json` as the primary import source.
- Keep raw normalized trajectory files as provenance references rather than duplicating all raw JSONL tables into transcripts.
- Treat this user request as confirmation to use the existing projection collection name and mapping documented in `ingestion-plan.md`.
- Avoid changing frontend dependencies or `bun.lock`.
- Use two local vLLM embedding endpoints:
  - Docent global embeddings: `BAAI/bge-small-zh-v1.5` on `http://localhost:8001/v1`, native 512 dimensions.
  - Hodoscope embeddings: `Qwen/Qwen3-Embedding-0.6B` on `http://localhost:8000/v1`, native 1024 dimensions.

## Errors Encountered
- Initial reads of Docent ingestion/analysis docs used the wrong path; corrected to `skills/docent/ingestion.md` and `skills/docent/analysis.md`.
- `python` is not available on PATH; use `python3` or `uv run python`.
- `jinaai/jina-embeddings-v2-small-en` is native 512 but unsupported by vLLM 0.10.2 because its architecture is `JinaBertForMaskedLM`.
- Both selected local embedding models reject explicit OpenAI `dimensions` requests; use `DOCENT_EMBEDDING_DIMENSIONS=auto` and `DOCENT_HODOSCOPE_EMBEDDING_DIMENSIONS=auto`, then verify returned vector length.
- First Hodoscope start failed with a foreign-key violation because the job row was not flushed before creating `hodoscope_analyses.job_id`; fixed in `HodoscopeService.start_or_get_analysis`.
- Direct Hodoscope REST calls returned 401; reused the same local signup/login cookie flow as the import script.
- First authenticated Hodoscope job failed because the local worker did not have the real `DEEPSEEK_API_KEY`; copied the key from `/data/lyuwt/Agent-Test/.env` into ignored local `.env` without printing it.
- Second authenticated job failed for 18 of 242 summaries because `max_new_tokens=256` was too small for DeepSeek flash with thinking enabled; raised Hodoscope-only summary budget to 1024.

## Status
**Complete** - imported 89 Agent-Test projected AgentRuns into collection `a63232a9-372f-40d5-9871-df52fc624a47`; completed Hodoscope analysis `745f1359-d73d-4c95-b119-3ce0a4a1a959` with 242 points, 1 group, `tsne` projection, and 1024-dimensional decoded Hodoscope embeddings.

---

# Task Plan: Resizable Workspace And Interactive Hodoscope Embedding

## Goal
Make the main Docent workspace panes drag-resizable with persisted layouts, and turn the Hodoscope embedding into a modern exploratory map with usable zoom, pan, filtering, selection, keyboard/touch fallbacks, and a responsive inspector.

## Scope Boundary
- P0: Reuse the installed `react-resizable-panels`; do not add frontend dependencies or change `bun.lock`.
- P0: Preserve dashboard, transcript, rubric, Hodoscope job, artifact download, and deep-link behavior.
- P0: Remove the current non-uniform SVG distortion and separate hover preview from committed selection/navigation.
- P0: Keep the full Hodoscope artifact downloadable while returning a lightweight projection view to the browser.
- P1: Persist only personal panel sizes in local storage; keep transient hover, map drag, zoom, and point selection ephemeral.
- P1: Preserve semantic light/dark theme tokens, keyboard resizing, pointer/touch selection, and narrow-layout fallbacks.
- P2: Do not migrate the formal 3021 deployment in this pass unless the product-source implementation and runtime checks pass first.

## Phases
- [x] Phase 1: Inspect product source, formal deployment ancestry, current layouts, renderer, data shape, and runtime boundaries.
- [x] Phase 2: Record the panel and visualization technical design.
- [x] Phase 3: Implement reusable modern resize handles and resizable dashboard/agent-run/experiment panes.
- [x] Phase 4: Implement the interactive Hodoscope embedding and lightweight projection response.
- [x] Phase 5: Run focused Python tests, frontend lint/build, and browser interaction/visual checks.
- [x] Phase 6: Report exact changed and untouched paths plus the deployment boundary.

## Key Decisions
- Product source of truth is `/data/lyuwt/docent-inner`; the formal 3021 tree is an older dirty deployment copy with no Hodoscope backend or frontend and must not be overwritten wholesale.
- Use a calm research-workspace visual direction: one dominant evidence viewport, compact command bars, restrained borders, visible selection, and no decorative 3D/particle effects.
- React owns filters, committed selection, routing, panel persistence, and inspector state; the existing hand-authored SVG owns normalized coordinates and marks.
- Keep one SVG instance per page. The normal live dataset has 242 points and the configured upper bound is 5000; use group-level transforms for pan/zoom rather than rerendering geometry on every pointer move where possible.
- Use explicit zoom controls plus wheel zoom, pointer pan, tap/click selection, double-click or an explicit Open action for navigation, and keyboard point stepping as the non-pointer path.
- Panel layouts use stable `autoSaveId` keys. Incoming URL state is unchanged; Hodoscope hover, selection, filter, and viewport are intentionally not written into the URL in this pass.
- The projection endpoint should omit full embeddings, raw action text, and full metadata from the browser payload; keep those fields in the artifact endpoint and return a bounded context excerpt for the inspector.

## Errors Encountered
- The formal 3021 deployment copy predates Hodoscope, so product-source verification used isolated ports 3001/8889 instead of overwriting that dirty runtime tree.
- A first compact-response implementation changed the legacy `/projection` contract; the final route keeps the full response by default and makes `compact=true` explicit.
- Conditional panel keys initially remounted viewer subtrees and invalidated saved layouts; stable React reconciliation keys and panel-ID combinations now preserve state.
- Browser QA sees the pre-existing anonymous Transcript Chat 401 when Chat is selected. It is not treated as a resize/Hodoscope regression, and the existing permission policy was left unchanged.
- The configured run limit could create far more SVG points than its label implied; the UI now recommends at most 500 loaded runs and new jobs separately cap/stratify 500-5000 action points while the backend retains the legacy API validation range.

## Status
**Complete** - Product-source UI, compact projection path, bounded new-job sampling, tests, production build, browser interaction checks, and isolated runtime smoke checks are complete.

---

# Task Plan: Rebuild And Online Current Docent

## Goal
Stop the older Docent Docker deployments and bring the current `/data/lyuwt/docent-inner` source online from freshly rebuilt images without deleting database volumes.

## Phases
- [x] Phase 1: Inventory both Docker daemons, current source state, ports, data volumes, and embedding dependencies
- [x] Phase 2: Stop and remove old Docent application/dependency containers while preserving volumes
- [x] Phase 3: Rebuild backend/frontend/worker from the current worktree and apply migrations
- [x] Phase 4: Start one current deployment and verify frontend, API, worker, Postgres, Redis, embeddings, and preserved data
- [x] Phase 5: Record exact runtime state, ports, changed files, and remaining limits

## Key Decisions
- Rebuild application images from the dirty current worktree at HEAD `a5ad148946e8`; do not commit, discard, or rewrite the user's source changes.
- Preserve `docent_inner_pgdata` and the rootless formal deployment volume; do not run `docker compose down -v` or delete any Docker volume.
- Reuse `docent_inner_pgdata` for the rebuilt deployment so the existing 1 collection and 89 AgentRuns remain available.
- Restart the two active local vLLM embedding containers, but remove obsolete exited Docent embedding containers.
- Use a local Compose override for host embedding routing and the existing Postgres volume so deployment-specific wiring does not alter tracked product source.
- Because host firewall policy blocks bridge-to-host traffic, the final local runtime uses host networking for frontend/backend/worker. This trades network isolation for working local GPU embedding access; Postgres/Redis remain normal published bridge services.

## Errors Encountered
- The first redacted `docker compose config` inspection failed because the jq filter called `with_entries` on services with no environment block; corrected the inspection filter to default null environments to `{}`. The Compose configuration itself had not been applied.
- The first `docker compose build --no-cache` stopped during base-image metadata resolution because the daemon mirror `xget.lyuwentao.workers.dev` timed out for `python:3.12-slim` and `node:22-alpine`; no source build step ran. Recovery is to verify local base images and rebuild without registry resolution, or preload only the missing base image if required.
- The first local-only rebuild was intentionally interrupted while still sending build context: `.dockerignore` did not exclude nested `docent_core/_web/node_modules` (938 MB) or `.next` (740 MB), and Compose was sending the same growing context for backend and worker. Added nested ignore rules and configured worker to reuse the freshly built backend image.
- The optimized backend build reached dependency installation but failed because the locked Hodoscope dependency is Git-sourced and `python:3.12-slim` has no `git` executable. Added minimal `git` and `ca-certificates` installation to `Dockerfile.backend` before running `uv`.
- The next backend build compiled local packages and fetched Hodoscope, then failed building `annoy==1.17.3` because no Python 3.12 wheel was available and `g++` was absent. Added `g++` to the backend image build dependencies.
- With the compiler available, a later no-cache build failed because GitHub terminated the TLS connection while fetching the already pinned Hodoscope commit. The exact commit wheel already exists in the host uv cache; the deployment build will inject that verified wheel temporarily without changing `uv.lock`.
- The first local-wheel build still resolved the project's `-e .` entry and detected conflicting Git/local Hodoscope URLs. The temporary deployment Dockerfile now removes only `-e .` from the exported dependency list, installs all locked dependencies including the exact local wheel, then installs Docent editable with `--no-deps` after copying source.
- A patch to assign the frontend image in the local override initially targeted a nonexistent frontend block; after inspecting the override, added the block at the correct service level. No runtime state was affected.
- The first frontend Dockerfile patch used a stale upstream-comment hash in its context and did not apply; re-read the live file before applying the targeted change.
- Frontend build failed because `Dockerfile.frontend` used `npm ci` while the repository has no `package-lock.json` and uses `bun.lock`. Switched dependency install/build stages to pinned `oven/bun:1.3.14-alpine` with `bun install --frozen-lockfile` and `bun run build`; the production runner remains `node:22-alpine`.
- First dependency-service startup stopped before container creation because local `redis:alpine` was absent and Compose attempted the timed-out daemon mirror. Preload that exact image with `regctl` and retry before migration.
- Postgres/Redis then started successfully, but Alembic could not read owner-only `pyproject.toml` as the non-root `docent` user; most source files are also mode 600. Added a final `/app` ownership transfer to `Dockerfile.backend` and the deployment image before retrying migration.
- After permissions were fixed, Alembic reached the database but used host-published `DOCENT_PG_PORT=55432` inside the Compose network, where Postgres listens on 5432. Added explicit internal `DOCENT_PG_PORT=5432` and `DOCENT_REDIS_PORT=6379` overrides for backend and worker; published host ports remain unchanged.
- The first complete stack reached healthy frontend/backend endpoints, but final security inspection found `Dockerfile.backend` copied local `.env` into the image despite Compose already injecting it. Removed that COPY and rebuild the backend/worker image so secrets are not present in the final image layers.
- The secret-free image then exposed that `load_dotenv()` required `/app/.env` even under `ENV_RESOLUTION_STRATEGY=os_environ`, causing backend child processes and worker restarts. Updated that mode to permit a missing file and added focused tests while preserving strict missing-file behavior for the default strategy.
- Final embedding smoke showed both vLLM endpoints healthy on the host but all host addresses timed out from the Compose bridge. Use a local host-network deployment file for frontend/backend/worker so they can reach localhost embeddings and published Postgres/Redis; keep the repository's default bridge Compose mode unchanged.
- The first combined patch for the host-network deployment used a stale task-plan insertion context and did not apply; re-read the live plan and applied the file plus notes against current content.
- The minimal backend image does not include `ps`, so an in-container process-list check failed; `docker top docent_worker` confirmed one parent plus two worker child processes instead.

## Status
**Complete** - old Docent containers are removed, current images are rebuilt and online, data/migrations/endpoints/embeddings are verified, and the durable local runtime spec is `/home/lyuwt/.config/docent-inner/docker-compose.online.yml`.
