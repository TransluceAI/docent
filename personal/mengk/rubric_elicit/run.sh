#!/bin/bash

# Bridgewater
# python3 label_elicitation.py \
#     da2d9ea5-9bf3-4347-9401-8bdae71de2d9 \
#     93484b14-f438-4b44-8682-113c354ce4ea \
#     --feedback-num-samples 25 \
#     --feedback-max-questions 10 \
#     --label-num-samples 25 \
#     --max-label-requests 5

# Bridgewater (entropy-only)
python3 label_elicitation_entropy_only.py \
    da2d9ea5-9bf3-4347-9401-8bdae71de2d9 \
    93484b14-f438-4b44-8682-113c354ce4ea \
    --label-num-samples 25 \
    --top-n 10
    # --user-data-json outputs/user_data_20260218_230218_gitignore.json
    # --label-num-samples 100 \
    # --top-n 20 \

# SWE-Bench
# python3 label_elicitation.py \
#     96fad7bd-eb81-4da6-95d9-d66e94ff1533 \
#     66e6e162-087a-4f99-8352-094e90b0e902 \
#     --feedback-num-samples 25 \
#     --feedback-max-questions 5 \
#     --label-num-samples 25 \
#     --max-label-requests 5
#     # --where-clause "metadata_json ->> 'instance_id' = 'astropy__astropy-13977'"
