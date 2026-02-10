# Label Elicitation Prototype

Standalone runner for rubric label elicitation, extracted from Docent Core internals.

It runs a two-stage process:

1. Feedback elicitation rounds to build/update a user model.
2. Label queue prioritization by disagreement score `H[p_u, p_j]`, then generation of structured labeling requests.

## Prerequisites

- Python 3.11+ (recommended)
- Docent SDK: `docent-python` (must provide `docent.*` imports)
- Additional packages:
  - `pydantic`
  - `rich`
  - `beaupy`

Example install:

```bash
# If you do not have a virtual environment yet:
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install docent-python pydantic rich beaupy
```

## Required Environment Variables

- `DOCENT_API_KEY`: API key used by `Docent(...)`
- `DOCENT_DOMAIN`: Docent domain

## Run

From this directory:

```bash
python label_elicitation.py <collection_id> <rubric_id> [options]
```

## Quickstart

For [this rubric in a BW collection](https://docent-bridgewater.transluce.org/dashboard/07287acb-8908-4f4c-95ec-8cdeadcb4423/rubric/a79933ef-a553-46bd-ae15-5e1c3f601549):

```bash
OPENAI_API_KEY=... DOCENT_API_KEY=... DOCENT_DOMAIN=docent-bridgewater.transluce.org python3 label_elicitation.py \
  07287acb-8908-4f4c-95ec-8cdeadcb4423 \
  a79933ef-a553-46bd-ae15-5e1c3f601549 \
  --feedback-num-samples 50 \
  --feedback-max-questions 10 \
  --label-num-samples 50 \
  --max-label-requests 10 \
  --cross-entropy-epsilon 1e-2
```

If you want to try this on a different collection or rubric, create a new rubric using the same initial description, then swap the `<rubric_id>` in the command above to that new rubric ID (and update `<collection_id>` as needed).

## Arguments

### Positional

- `collection_id` (str): Collection ID.
- `rubric_id` (str): Rubric ID.

### Optional

- `--label-set-id` (str, default: `None`)
  - Optional label set ID used to seed user data with existing labels.

- `--server-url` (str, default: `http://localhost:8902`)
  - Docent API server URL.

- `--feedback-rounds` (int, default: `1`, minimum: `1`)
  - Number of interactive feedback rounds.

- `--feedback-num-samples` (int, default: `50`, must be `> 0`)
  - Number of agent runs sampled for feedback question extraction.

- `--feedback-max-questions` (int, default: `10`, must be `> 0`)
  - Max number of selected feedback questions per round.

- `--feedback-max-questions-per-run` (int, default: `3`, must be `> 0`)
  - Max extracted questions per sampled run before dedup/selection.

- `--label-num-samples` (int, default: `50`, must be `> 0`)
  - Number of agent runs sampled for label-queue ranking.

- `--max-label-requests` (int, default: `20`, must be `> 0`)
  - Max ranked runs to generate labeling requests for.

- `--seed` (int, default: `0`)
  - Random seed for sampling runs.

- `--include-labeled-runs` (flag, default: `False`)
  - Include already labeled runs in label-stage sampling.

- `--cross-entropy-epsilon` (float, default: `1e-2`, must be `> 0`)
  - Smoothing constant used when computing `H[p_u, p_j]`.

## Notes

- The feedback stage is interactive and expects a TTY (uses `beaupy` + `rich` prompts).
- If `--label-set-id` is omitted, the user model starts from rubric text only.
