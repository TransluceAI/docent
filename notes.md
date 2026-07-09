# Notes: Multi-Transcript Actions Summary

## Current State
- Repository: `/data/lyuwt/docent-inner`
- Branch: `main`
- Initial git status for this task:
  - `?? AGENTS.md`
  - `?? notes.md`
  - `?? task_plan.md`
- Current endpoint: `docent_core/docent/server/rest/router.py` only analyzes `agent_run.transcripts[0]`.
- Current summarizer rendering: `docent_core/docent/ai_tools/assistant/summarizer.py` calls `transcript.to_str(use_action_units=True)[0]`, which defaults to `transcript_idx=0`.
- Current frontend type: `ActionsSummary` only has `agent_run_id`, `low_level`, `high_level`, and `observations`.
- Current frontend UI: `AgentSummary.tsx` renders one action sequence and high-level action clicks use `transcript_idx: undefined`.

## Implementation Notes
- `AgentRun.get_transcript_ids_ordered(full_tree=False)` gives canonical transcript order.
- `agent_run.transcript_dict` maps those IDs to `Transcript` objects.
- `Transcript` has `name`, `id`, and `transcript_group_id`; all are useful for selector labels.
- `AgentRunViewer` already supports citation navigation with `transcript_idx`, so the main bug is producing and passing the correct index.

## Verification Targets
- Python unit tests for summarizer `transcript_idx` forwarding and backend transcript aggregation.
- Frontend lint/build if dependencies are available.
- `git diff --check` before final report.

## DeepSeek Provider Notes
- Official docs list OpenAI-compatible base URL: `https://api.deepseek.com`.
- Current API model names are `deepseek-v4-flash` and `deepseek-v4-pro`.
- DeepSeek docs show `max_tokens`, not `max_completion_tokens`.
- DeepSeek docs list `reasoning_effort` values `high` and `max`; compatibility maps lower efforts to `high`.
- The pasted API key is not stored in repo changes; `.env` should use `DEEPSEEK_API_KEY=` locally.

## Verification Results
- `uv run --extra dev pytest tests/unit/test_actions_summary.py tests/unit/test_deepseek_preferences.py -q`: 7 passed.
- `uv run --extra dev pytest tests/unit -q`: 30 passed.
- `uv run --extra dev pyright docent_core/_llm_util/providers/deepseek.py docent_core/_llm_util/providers/preferences.py docent_core/_llm_util/providers/registry.py docent_core/docent/server/rest/router.py docent_core/docent/ai_tools/assistant/summarizer.py`: 0 errors.
- `uv run --extra dev python -m compileall -q ...`: passed.
- `git diff --check`: passed.
- Installed Bun for user `lyuwt`: `/home/lyuwt/.bun/bin/bun`, version `1.3.14`.
- Updated `/home/lyuwt/.profile` so login shells can resolve `bun`.
- `bun install --frozen-lockfile`: failed because `bun.lock` was stale relative to `package.json`.
- `bun install`: passed and refreshed `docent_core/_web/bun.lock`.
- `bun run lint`: passed with 0 errors and 106 existing warnings after changing the script from removed `next lint` to `eslint . --ext .ts,.tsx`.
- `NEXT_PUBLIC_API_HOST=http://localhost:8888 NEXT_PUBLIC_INTERNAL_API_HOST=http://localhost:8888 bun run build`: passed.
- Build-time fixes needed for Next 16: dynamic `params` in `app/dashboard/[collection_id]/layout.tsx`, `headers()`/`cookies()` await, and a guard for missing `agent_run_id` in the agent run page.

## LLM Provider Configuration Update
- Added `DOCENT_LLM_PROVIDER`, `DOCENT_LLM_BASE_URL`, `DOCENT_LLM_API_KEY`, `DOCENT_LLM_FLASH_MODEL`, and `DOCENT_LLM_PRO_MODEL` as the self-hosting configuration surface.
- Default configuration remains DeepSeek with `deepseek-v4-flash` for fast/cheap paths and `deepseek-v4-pro` for stronger paths.
- Added `custom` provider for OpenAI-compatible chat-completions endpoints. It uses `DOCENT_LLM_BASE_URL` and `DOCENT_LLM_API_KEY`.
- Added per-feature model overrides for chat, judge, action summaries, observations, search, refinement, clustering, query generation, and intended-solution summarization.
- Added matching `_REASONING_EFFORT` env vars for model-specific reasoning effort overrides.
- Docker Compose now passes the project root `.env` into backend and worker through `env_file`.
- Updated self-host docs:
  - `docs/self_hosting/environment_variables.md`
  - `docs/self_hosting/llm_providers_and_calls.md`
  - `docs/self_hosting/self_host_docent.md`

## LLM Provider Configuration Verification
- `uv run --extra dev pytest tests/unit/test_deepseek_preferences.py -q`: 8 passed.
- `uv run --extra dev pyright docent_core/_llm_util/providers/preferences.py docent_core/_llm_util/providers/custom.py docent_core/_llm_util/providers/deepseek.py docent_core/_llm_util/providers/registry.py docent_core/docent/server/rest/router.py`: 0 errors.
- `uv run --extra dev python -m compileall -q docent_core/_llm_util/providers/preferences.py docent_core/_llm_util/providers/custom.py docent_core/_llm_util/providers/deepseek.py docent_core/_llm_util/providers/registry.py docent_core/docent/server/rest/router.py`: passed.
- `uv run --extra dev pytest tests/unit -q`: 34 passed.
- `bun run lint`: passed with 0 errors and 106 existing warnings.
- `NEXT_PUBLIC_API_HOST=http://localhost:8888 NEXT_PUBLIC_INTERNAL_API_HOST=http://localhost:8888 bun run build`: passed.
- `uv.lock` was restored to HEAD after `uv` rewrote registry URLs to a local mirror.

---

# Notes: Docent-Native Hodoscope Analysis Layer

## Current State
- Repository: `/data/lyuwt/docent-inner`
- Branch: `main`, ahead of `origin/main` by 1 commit before this implementation.
- `hodoscope_notes.md` and `hodoscope_task_plan.md` contain the prior read-only exploration.
- Existing chart dashboard area lives in `docent_core/_web/app/components/ExperimentViewer.tsx`.
- Existing background jobs use `SQLAJob`, `WorkerFunction`, Redis enqueueing, and `JOB_DISPATCHER_MAP`.

## Implementation Notes
- Add a new service/router rather than expanding `docent_core/docent/server/rest/router.py`.
- Use Docent action units for native links: `agent_run_id`, `transcript_idx`, `first_block_idx`.
- Store Hodoscope-compatible JSON and UI projection JSON in the same analysis row.
- Use upstream Hodoscope pure projection/FPS helpers only after Docent has produced summaries and embeddings.
- Add frontend without new npm/bun dependencies.

## Verification Targets
- Backend unit tests for extraction, artifact/projection shape, small projection fallback, and active-job reuse.
- Python compile/import check for new modules.
- Focused unit tests before broader pre-commit.
- Frontend lint/build if time and dependency state allow.

## Implementation Results
- Added pinned upstream `hodoscope` dependency in `pyproject.toml` and intentionally updated `uv.lock`.
- Added `hodoscope_analyses` SQLAlchemy table and Alembic migration `a2e2b7c9142a_add_hodoscope_analyses.py`.
- Added `HodoscopeService`, `hodoscope_analysis_job`, and a Docent-owned pipeline for action extraction, Docent LLM summaries, OpenAI embeddings, Hodoscope projection/FPS helpers, JSONB artifact storage, and projection storage.
- Added `WorkerFunction.HODOSCOPE_ANALYSIS` and registered it in `JOB_DISPATCHER_MAP`.
- Added `/rest/hodoscope/{collection_id}/analyses` start/list/get/projection/artifact/cancel endpoints.
- Added `PROVIDER_PREFERENCES.hodoscope_action_summaries`, defaulting through the flash model env path.
- Added frontend `hodoscopeApi`, store registration, and `HodoscopePanel` under charts and above the Agent Run List.
- The Hodoscope map is user-triggered only; dashboard load lists prior analyses but does not start new jobs.

## Verification Results
- `uv run pytest -m unit -v tests/unit/test_hodoscope_analysis.py`: 5 passed.
- `uv run pytest -m integration -v tests/integration/test_hodoscope_analysis.py`: blocked by local Postgres authentication (`InvalidPasswordError` for `docent_user` on `_pytest_docent_test`).
- `uv run python -m compileall -q ...`: passed for new backend modules and tests.
- `uv run pre-commit run --files ...`: passed for the Hodoscope change set.
- `uv run alembic upgrade e4255c1640a7:a2e2b7c9142a --sql`: generated valid static SQL for the migration.
- `git diff --check`: passed.
- `bun run lint`: passed with existing repository warnings only.
- `NEXT_PUBLIC_API_HOST=http://localhost:8889 bun run build`: passed.

---

# Notes: Live Hodoscope Validation With Agent-Test Trajectory

## Source And Key Discovery
- Requested path `/data/lyuwt/Agent-test` does not exist; actual workspace path is `/data/lyuwt/Agent-Test`.
- Key source inspected without printing values: `/data/lyuwt/Agent-Test/.env`.
- Present key variables: `DEEPSEEK_API_KEY`, `DOCENT_API_KEY`.
- No `OPENAI_API_KEY` was found in `/data/lyuwt/Agent-Test/.env` or `/data/lyuwt/docent-inner/.env`.
- Compact trajectory surface: `/data/lyuwt/Agent-Test/docent_projection/dist/agent_runs.json`.
- Canonical clean result root: `/data/lyuwt/Agent-Test/tbench/benchmarks/runs/claudecode-deepseek-v4-flash-c16-cache-20260707/clean_result`.

## Source Counts
- `agent_runs.json`: 89 projected runs.
- `normalized/trials.jsonl`: 89 rows.
- `normalized/trajectory_steps.jsonl`: 2837 rows.
- `normalized/model_io.jsonl`: 5999 rows.
- `normalized/tool_events.jsonl`: 3262 rows.

## Live Extraction Result
- Converted first 5 projected runs into Docent SDK `AgentRun` objects using their `docent_messages`.
- Converted OpenAI-style assistant `tool_calls` into Docent SDK `ToolCall` shape in the temporary validation harness.
- `extract_hodoscope_actions` output: 186 action points from 5 sample runs.
- Default group-by detected: `metadata.model`.
- Groups: `deepseek-v4-flash: 186`.
- First point: `transcript_idx=0`, `action_unit_idx=0`, `first_block_idx=0`, action text length 8702 chars.

## Live Summary Result
- A real DeepSeek-backed `summarize_hodoscope_actions` call completed using `/data/lyuwt/Agent-Test/.env`.
- Initial output copied tool-call markup instead of following the two-line action-summary format.
- Tightened `HODOSCOPE_SUMMARY_PROMPT` and wrapped action text as inert transcript data.
- Retest on the same action returned:
  - `Action: Checked if R is installed, but it failed.`
  - `For: Verified environment before implementing the sampler.`

## Live Embedding And Projection Result
- Both `/data/lyuwt/Agent-Test/.env` and `/data/lyuwt/docent-inner/.env` lack `OPENAI_API_KEY` / `OPENAI_ADMIN_KEY`.
- `embed_hodoscope_summaries` now fails before making an OpenAI request with: `Hodoscope embeddings require OPENAI_API_KEY or OPENAI_ADMIN_KEY for text-embedding-3-small.`
- Projection smoke test with 3 real action records and fake 512-dimensional embeddings succeeded: `projection_method=tsne`, 3 points, group `deepseek-v4-flash`.

---

# Notes: OpenAI-Compatible Embedding Alignment

## Implementation Results
- `docent_core/_llm_util/providers/openai.py` now has a dedicated OpenAI-compatible embedding client path.
- Embedding env resolution order:
  - Base URL: `DOCENT_EMBEDDING_BASE_URL`, then `OPENAI_BASE_URL`, then `DOCENT_LLM_BASE_URL` when `DOCENT_LLM_PROVIDER=custom`.
  - API key: `DOCENT_EMBEDDING_API_KEY`, then `DOCENT_LLM_API_KEY` when `DOCENT_LLM_PROVIDER=custom`, then `OPENAI_API_KEY` / `OPENAI_ADMIN_KEY`.
  - Model: `DOCENT_EMBEDDING_MODEL`, defaulting to `text-embedding-3-small`.
  - Dimensions: `DOCENT_EMBEDDING_DIMENSIONS` / `DOCENT_EMBEDDING_DIM`, with `auto`, `none`, and `null` meaning do not send the OpenAI `dimensions` parameter.
- The chunked embedding helper now sends text chunks to the embeddings endpoint instead of token-id chunks. This keeps hosted OpenAI compatibility and improves compatibility with OpenAI-compatible local embedding servers.
- `HodoscopeAnalysisConfig` now resolves embedding defaults from env and supports `DOCENT_HODOSCOPE_EMBEDDING_MODEL` plus `DOCENT_HODOSCOPE_EMBEDDING_DIMENSIONS` for Hodoscope-only local embedding use.
- `hodoscope_worker` passes the persisted analysis config's embedding model and dimensions into `embed_hodoscope_summaries`.
- `.env.template` and `docs/self_hosting/environment_variables.md` now document embedding configuration.

## Boundary
- Docent's existing transcript embedding table is `vector(512)`. For local embedding models that return non-512 vectors, use the Hodoscope-only env vars first:
  - `DOCENT_HODOSCOPE_EMBEDDING_MODEL=<local-model>`
  - `DOCENT_HODOSCOPE_EMBEDDING_DIMENSIONS=auto`
- Only set the global `DOCENT_EMBEDDING_MODEL` to a non-512 model if the transcript embedding storage path is also migrated.

## Verification Results
- `uv run python -m compileall -q docent_core/_llm_util/providers/openai.py docent_core/docent/services/hodoscope.py docent_core/docent/services/hodoscope_pipeline.py docent_core/docent/workers/hodoscope_worker.py tests/unit/test_hodoscope_analysis.py`: passed.
- `uv run pytest -m unit -v tests/unit/test_hodoscope_analysis.py`: 11 passed.
- `uv run pre-commit run --files docent_core/_llm_util/providers/openai.py docent_core/docent/services/hodoscope.py docent_core/docent/services/hodoscope_pipeline.py docent_core/docent/workers/hodoscope_worker.py tests/unit/test_hodoscope_analysis.py .env.template docs/self_hosting/environment_variables.md task_plan.md notes.md`: passed.
- `git diff --check`: passed.

---

# Notes: Local Qwen3 Embedding vLLM Server

## Runtime Selection
- Host GPU: NVIDIA GeForce RTX 4090, 24GB class VRAM.
- Host driver: `570.195.03`, `nvidia-smi` reports CUDA `12.8`.
- Final Docker image: `vllm/vllm-openai:v0.10.2`, size `22.5GB`.
- Rejected Docker image: `vllm/vllm-openai:latest`, because it used `torch 2.11.0+cu130` and failed on this CUDA 12.8 host.
- Model: `Qwen/Qwen3-Embedding-8B`.
- Service URL: `http://localhost:8000/v1`.
- Container name: `docent-qwen3-embedding-vllm`.
- Model cache: `/data/lyuwt/.cache/huggingface`.
- Downloaded image tar:
  - `/data/lyuwt/docker-images/vllm-openai-v0.10.2-linux-amd64.tar`
- Helper binary used to bypass Docker daemon proxy issues:
  - `/data/lyuwt/tools/regctl`

## Final vLLM Optimizations
- CUDA graph enabled through vLLM default optimized mode.
- Flash Attention backend enabled.
- Prefix caching enabled.
- Chunked prefill enabled.
- `torch.compile` enabled; startup log reported dynamic graph compile.
- Startup log reported CUDA graph capture completed.
- `max_model_len=8192`.
- `max_num_seqs=16`.
- `gpu_memory_utilization=0.90`.
- `TORCH_CUDA_ARCH_LIST=8.9` for the RTX 4090.

## Deployment Notes
- Docker daemon does not have a working NVIDIA Container Toolkit install:
  - `--gpus all` failed with no GPU device driver.
  - `--runtime=nvidia` failed because `nvidia-container-runtime` is missing.
- The container is started with manual GPU passthrough:
  - `/dev/nvidia0`
  - `/dev/nvidiactl`
  - `/dev/nvidia-uvm`
  - `/dev/nvidia-uvm-tools`
  - host `libcuda` and `libnvidia-ml` mounts.
- The container uses `--network host` so the existing shell proxy at `127.0.0.1:1283` is reachable inside the container during model downloads.
- `--restart unless-stopped` is enabled.

## Docent Configuration
- Local `.env` now includes non-secret embedding settings:
  - `DOCENT_EMBEDDING_BASE_URL=http://localhost:8000/v1`
  - `DOCENT_EMBEDDING_API_KEY=dummy`
  - `DOCENT_HODOSCOPE_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B`
  - `DOCENT_HODOSCOPE_EMBEDDING_DIMENSIONS=auto`
- This routes Hodoscope embeddings to local vLLM and avoids sending the OpenAI `dimensions` parameter.
- The embedding output is 4096-dimensional, so this should remain Hodoscope-only unless Docent's fixed `vector(512)` transcript embedding table is migrated.

## Verification Results
- `docker run --entrypoint python3 vllm/vllm-openai:v0.10.2 ... torch.cuda.is_available()`: passed; saw RTX 4090 with torch `2.8.0+cu128`.
- vLLM startup logs confirmed:
  - supported tasks: `['embed']`
  - `/v1/embeddings` route available
  - CUDA graph capture finished
  - Flash Attention backend on V1 engine
  - prefix caching and chunked prefill enabled.
- `curl http://localhost:8000/v1/models`: returned `Qwen/Qwen3-Embedding-8B`.
- Direct `/v1/embeddings` smoke returned `embedding_dim 4096`.
- Docent/Hodoscope helper smoke from `.env` returned:
  - `embedding_model`: `Qwen/Qwen3-Embedding-8B`
  - `embedding_dimensionality`: `None`
  - `embedding_dim`: `4096`

---

# Notes: Agent-Test Import And Hodoscope Analysis

## Source Inspection
- Primary import source: `/data/lyuwt/Agent-Test/docent_projection/dist/agent_runs.json`.
- Projection bundle files present:
  - `collection_manifest.json` size 1307 bytes
  - `agent_runs.json` size 29057843 bytes
  - `agent_runs.jsonl` size 26673379 bytes
  - `docent_messages.jsonl` size 11363643 bytes
  - `label_schemas.json` size 5274 bytes
- `agent_runs.json` is a list with 89 records.
- First record keys include `docent_messages`, `final_state`, `metadata`, `name`, `run_id`, `sections`, `timeline`, and `verification_summary`.
- First metadata keys include `agent_scaffold`, `agent_version`, `artifact_counts`, `benchmark`, `condition`, `exception_type`, `model`, `paths`, `run_id`, `scores`, `task_id`, `task_name`, `terminal_outcome`, and `token_usage`.
- Manifest collection name: `Terminal-Bench 2.1 Claude Code DeepSeek V4 Flash c16 cache 20260707`.
- Raw normalized trajectory files present under `/data/lyuwt/Agent-Test/tbench/benchmarks/runs/claudecode-deepseek-v4-flash-c16-cache-20260707/clean_result/normalized`.

## Runtime Inspection
- Existing containers:
  - `docent-qwen3-embedding-vllm` is running.
  - `stockresearch-postgres` owns host port 5432.
  - Existing `redis` container exposes only container port 6379, not a host port.
- Local `.env` points Docent Postgres to `localhost:5432`, which currently conflicts with `stockresearch-postgres`.
- Local `.env` points Docent Redis to `localhost:6379`, but no host Redis port is currently published by the visible containers.

## Embedding Runtime Update
- Replaced the single 8B embedding container with two smaller vLLM endpoints:
  - `docent-embedding-512-vllm`: `BAAI/bge-small-zh-v1.5` on `http://localhost:8001/v1`, returned 512-dimensional embeddings.
  - `docent-hodoscope-embedding-1024-vllm`: `Qwen/Qwen3-Embedding-0.6B` on `http://localhost:8000/v1`, returned 1024-dimensional embeddings.
- `jinaai/jina-embeddings-v2-small-en` was tested and rejected because vLLM 0.10.2 does not support `JinaBertForMaskedLM`.
- Both selected local embedding models reject explicit OpenAI `dimensions` requests. Local `.env` therefore uses:
  - `DOCENT_EMBEDDING_DIMENSIONS=auto`
  - `DOCENT_HODOSCOPE_EMBEDDING_DIMENSIONS=auto`
- vLLM logs confirmed CUDA graph capture for both endpoints.
- vLLM logs confirmed Flash Attention for both endpoints.
- Hodoscope Qwen endpoint kept prefix caching and chunked prefill enabled.
- Docent BGE endpoint uses CLS pooling; vLLM disables prefix caching and chunked prefill for that pooling mode.

## Agent-Test Import Result
- Started local Docent dependencies without touching existing unrelated containers:
  - `docent_postgres` on host port `55432`
  - `docent_redis` on host port `56379`
- Ran local server on `http://localhost:8889` and worker with the local `.env`.
- Imported `/data/lyuwt/Agent-Test/docent_projection/dist/agent_runs.json`.
- Collection ID: `a63232a9-372f-40d5-9871-df52fc624a47`.
- Imported/verified AgentRuns: `89`.
- Import result file: `/tmp/docent_inner_agent_test_ingest_result.json`.
- Projection sample file: `/tmp/docent_inner_agent_test_projection_sample.json`.

## Hodoscope Smoke Result
- Completed analysis ID: `745f1359-d73d-4c95-b119-3ce0a4a1a959`.
- Completed job ID: `f8df9c51-dd76-4f5d-bbb6-d54f7005388b`.
- Config:
  - `limit=5`
  - `seed=42`
  - `projection_method=tsne`
  - detected group field `metadata.model`
  - embedding model `Qwen/Qwen3-Embedding-0.6B`
  - embedding dimensions omitted as `auto`
- Result:
  - status `complete`
  - points `242`
  - groups `1`
  - group `deepseek-v4-flash`
  - decoded first artifact embedding: `float32[1024]`
  - projection endpoint returned `200`
  - artifact endpoint returned `200`
- Output files:
  - `/tmp/docent_inner_hodoscope_smoke_status.json`
  - `/tmp/docent_inner_hodoscope_smoke_projection.json`
  - `/tmp/docent_inner_hodoscope_smoke_artifact.json`
  - `/tmp/docent_inner_hodoscope_smoke_result.json`

## Runtime Fixes From Smoke Test
- Hodoscope analysis creation initially hit a foreign-key violation because the job row was not flushed before the analysis row referenced it; fixed by flushing `sq_job` before adding `sq_analysis`.
- Hodoscope REST requires authentication; the successful smoke reused the local signup/login cookie flow from the import script.
- The first authenticated Hodoscope job failed before embedding because `DEEPSEEK_API_KEY` was missing from local `.env`; copied it from `/data/lyuwt/Agent-Test/.env` without printing the value.
- The next job failed for `18/242` action summaries with `CompletionTooLongException`; Hodoscope-only summary budget is now `1024` tokens.
- Final 1024-budget job reached embedding, projection, and artifact storage successfully.

## Verification Results
- Direct endpoint smoke:
  - `docent-512`: `BAAI/bge-small-zh-v1.5`, dimension `512`
  - `hodoscope-1024`: `Qwen/Qwen3-Embedding-0.6B`, dimension `1024`
- `uv run pytest -m unit -v tests/unit/test_hodoscope_analysis.py`: `13 passed`.
- `git diff --check`: passed.
