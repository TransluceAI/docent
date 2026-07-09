# Docent Ingestion Plan

## Configuration
- Data path: `/data/lyuwt/Agent-Test/docent_projection/dist/agent_runs.json`
- Raw trajectory path: `/data/lyuwt/Agent-Test/tbench/benchmarks/runs/claudecode-deepseek-v4-flash-c16-cache-20260707/clean_result/normalized`
- API key source: local self-host import first; `/data/lyuwt/Agent-Test/.env` has `DOCENT_API_KEY` for prior external/self-host access but values are not printed.

## Source Analysis
- File structure:
  - projection bundle: `agent_runs.json`, `agent_runs.jsonl`, `docent_messages.jsonl`, `collection_manifest.json`, `label_schemas.json`
  - raw normalized traj: `runs.jsonl`, `trials.jsonl`, `trajectory_steps.jsonl`, `model_io.jsonl`, `tool_events.jsonl`, `session_events.jsonl`, `environment_transitions.jsonl`, `verification.jsonl`
- Detected formats: projected Docent-like JSON plus raw normalized JSONL trajectory tables.
- Expected source record count: 89 projected AgentRuns.

## Docent Model Orientation
- Documentation reviewed:
  - `~/.codex/plugins/cache/transluce-plugins/docent/0.1.2/skills/docent/ingestion.md`
  - `~/.codex/plugins/cache/transluce-plugins/docent/0.1.2/skills/docent/analysis.md`
- Important SDK/model assumptions:
  - One projected task attempt becomes one Docent `AgentRun`.
  - `docent_messages` become one transcript in one transcript group.
  - Raw trajectory facts remain in metadata and source path references unless already normalized into the projection bundle.

## Proposed Docent Structure
- Collection: `Terminal-Bench 2.1 Claude Code DeepSeek V4 Flash c16 cache 20260707`
- AgentRun unit: one terminal-bench task attempt.
- TranscriptGroup usage: one default group per AgentRun.
- Transcript usage: one transcript containing the projected Docent messages.

## Field Mapping
| Source | Docent target | Notes |
| --- | --- | --- |
| `name` | `AgentRun.name` | Human-readable task/run name from projection. |
| `docent_messages` | `Transcript.messages` | Main behavior trace used by Docent and Hodoscope. |
| `metadata` | `AgentRun.metadata` | Includes model, benchmark, task_id, scores, paths, token usage, artifact counts. |
| `run_id` | `AgentRun.metadata.run_id` | Preserved for source lookup; Docent may assign its own UUID. |
| `sections`, `timeline`, `verification_summary`, `final_state` | `AgentRun.metadata` | Preserved as structured context when import path supports it. |
| raw normalized JSONL files | source references in metadata | Used for provenance; not duplicated into every transcript unless needed. |

## Omitted Data
| Field/File | Reason | Impact |
| --- | --- | --- |
| Full raw archive payloads outside projection bundle | The projection bundle already contains the compact transcript/action surface; importing every raw archive object would bloat the collection. | Deep links and source paths remain available; raw replay may require opening Agent-Test files directly. |
| Secret key values from `.env` | Security boundary. | No analysis impact. |

## Confirmation
- Collection name: treat current user request as confirmation to use the existing Agent-Test projection collection name.
- Data context: Terminal-Bench 2.1 Claude Code DeepSeek V4 Flash c16 cache run.
- Analysis goals: import local projected runs, then run the Docent-native Hodoscope behavior map using local Qwen3 embeddings.
- User confirmed: yes, by asking to import the prior data and traj now.

## Execution Log
- 2026-07-09: confirmed projection bundle exists and contains 89 AgentRuns.
- 2026-07-09: confirmed raw normalized trajectory files exist under `clean_result/normalized`.
- 2026-07-09: imported the projection bundle into local Docent collection `a63232a9-372f-40d5-9871-df52fc624a47`.
- 2026-07-09: ran Docent-native Hodoscope analysis `745f1359-d73d-4c95-b119-3ce0a4a1a959` with local vLLM Hodoscope embeddings.

## Verification
- Source records: 89 projected AgentRuns.
- Converted: 89 AgentRuns.
- Failed conversions: 0 reported by the import result.
- Uploaded: 89 AgentRuns verified through the local Docent API.
- Sanity warnings: two failed Hodoscope attempts were kept inspectable; final run completed after fixing local DeepSeek env and summary token budget.
- Collection URL: `http://localhost:3001/dashboard/a63232a9-372f-40d5-9871-df52fc624a47` if the local web server is started on port 3001.
- Hodoscope analysis: `745f1359-d73d-4c95-b119-3ce0a4a1a959`, status `complete`, 242 points, 1 group, `tsne`.
- Hodoscope outputs:
  - `/tmp/docent_inner_hodoscope_smoke_status.json`
  - `/tmp/docent_inner_hodoscope_smoke_projection.json`
  - `/tmp/docent_inner_hodoscope_smoke_artifact.json`
  - `/tmp/docent_inner_hodoscope_smoke_result.json`
