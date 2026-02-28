#!/bin/bash

##
# Bridgewater (confidential) (prod-bw)
##

# python3 label_elicitation.py \
#     137e5989-0840-48f5-8502-6b48b4e9905b \
#     cb26bb6f-0456-4f33-98f4-eda7265ff8de \
#     --label-num-samples 50 \
#     --top-n 10 \
#     --where-clause "metadata_json ->> 'training_step' = '300'"
#     # --where-clause "metadata_json @> '{\"training_step\": 200}'"

# python3 rubric_bon.py \
#     da2d9ea5-9bf3-4347-9401-8bdae71de2d9 \
#     93484b14-f438-4b44-8682-113c354ce4ea \
#     --k 10 \
#     --train-ratio 1 \
#     --seed 0 \
#     --user-data-json outputs/user_data_20260219_175322_gitignore.json

##
# Bridgewater (local)
##

# python3 label_elicitation.py \
#     da2d9ea5-9bf3-4347-9401-8bdae71de2d9 \
#     fb620aa5-a54b-4415-a7a7-74ce4acd4176 \
#     --label-num-samples 50 \
#     --top-n 10 \
#     --user-data-json outputs/user_data_20260219_175322_gitignore.json

# python3 rubric_bon.py \
#     da2d9ea5-9bf3-4347-9401-8bdae71de2d9 \
#     93484b14-f438-4b44-8682-113c354ce4ea \
#     --k 10 \
#     --train-ratio 1 \
#     --seed 0 \
#     --user-data-json outputs/user_data_20260219_175322_gitignore.json

##
# Cassidy (prod)
##

# python3 label_elicitation.py \
#     a75d95b8-c50b-4295-90d2-69c314f1220b \
#     67a641f2-3aad-4723-87ff-98ed55ee366b \
#     --label-num-samples 50 \
#     --top-n 10 \
#     # --user-data-json outputs/user_data_20260220_233137_gitignore.json

# python3 rubric_bon.py \
#     a75d95b8-c50b-4295-90d2-69c314f1220b \
#     67a641f2-3aad-4723-87ff-98ed55ee366b \
#     --k 10 \
#     --train-ratio 1 \
#     --seed 0 \
#     --user-data-json outputs/user_data_20260220_233137_gitignore.json

##
# SWE-Bench (local)
##

# python3 label_elicitation.py \
#     96fad7bd-eb81-4da6-95d9-d66e94ff1533 \
#     66e6e162-087a-4f99-8352-094e90b0e902 \
#     --label-num-samples 50 \
#     --top-n 10 \
#     --user-data-json outputs/user_data_20260220_222626_gitignore.json
#     # --where-clause "metadata_json ->> 'instance_id' = 'astropy__astropy-13977'"

##
# Terminal Bench (prod)
##

python3 label_elicitation.py \
    117967cf-d3bb-42e9-947d-eee82e97738f \
    433f5140-10cd-4d10-b192-0d4b01f665bb \
    --label-num-samples 50 \
    --top-n 10 \
#     --user-data-json outputs/user_data_20260225_185652_gitignore.json

# python3 rubric_bon.py \
#     117967cf-d3bb-42e9-947d-eee82e97738f \
#     433f5140-10cd-4d10-b192-0d4b01f665bb \
#     --k 10 \
#     --train-ratio 1 \
#     --seed 0 \
#     --user-data-json outputs/user_data_20260225_202634_gitignore.json
