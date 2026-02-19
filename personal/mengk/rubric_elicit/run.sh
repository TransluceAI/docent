#!/bin/bash

# Bridgewater (k-rubrics holdout evaluation)
python3 label_elicitation_k_rubrics_holdout.py \
    da2d9ea5-9bf3-4347-9401-8bdae71de2d9 \
    93484b14-f438-4b44-8682-113c354ce4ea \
    --k 5 \
    --train-ratio 1 \
    --seed 0 \
    --user-data-json outputs/user_data_20260219_154928_gitignore.json

# Bridgewater (entropy-only)
# python3 label_elicitation_entropy_only.py \
#     da2d9ea5-9bf3-4347-9401-8bdae71de2d9 \
#     93484b14-f438-4b44-8682-113c354ce4ea \
#     --label-num-samples 50 \
#     --top-n 10 \
#     --user-data-json outputs/user_data_20260219_154928_gitignore.json

# SWE-Bench (entropy-only)
# python3 label_elicitation_entropy_only.py \
#     96fad7bd-eb81-4da6-95d9-d66e94ff1533 \
#     66e6e162-087a-4f99-8352-094e90b0e902 \
#     --label-num-samples 25 \
#     --top-n 10
#     # --where-clause "metadata_json ->> 'instance_id' = 'astropy__astropy-13977'"
