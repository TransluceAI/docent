# Label Elicitation Prototype (Entropy-Only)

Standalone runner for entropy-prioritized rubric label elicitation.

Pipeline:
1. Load rubric and infer a user model from existing `UserData`.
2. Sample agent runs.
3. Estimate user distributions `p_u(y | x, z, r)`.
4. Rank runs by Shannon entropy `H[p_u]` on rubric agreement keys.
5. Generate labeling requests and collect user labels.

## Run

From `personal/mengk/rubric_elicit/`:

```bash
python label_elicitation_entropy_only.py <collection_id> <rubric_id> [options]
```

## Quickstart

```bash
OPENAI_API_KEY=... DOCENT_API_KEY=... DOCENT_DOMAIN=docent-bridgewater.transluce.org \
python3 label_elicitation_entropy_only.py \
  <collection_id> \
  <rubric_id> \
  --label-num-samples 50 \
  --top-n 10
```

## Notes

- This runner does not run rubric-judge `p_j` and does not compute cross-entropy `H[p_u, p_j]`.
- Use `--user-data-json` to seed user-model inference with prior QA/labels.
