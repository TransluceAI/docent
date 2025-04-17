#!/bin/bash
set -e

# Check for MONOREPO_ROOT environment variable and navigate to it
if [ -z "${MONOREPO_ROOT}" ]; then
    echo "Error: MONOREPO_ROOT environment variable is not set"
    exit 1
fi
cd "${MONOREPO_ROOT}"

# Run python script under sudo, passing stdin through
# sudo overrides env vars so we need to pass them back in
sudo OPENAI_API_KEY=$OPENAI_API_KEY ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY MORPH_API_KEY=$MORPH_API_KEY .venv/bin/python project/docent/docent/experiments/run_inspect_experiment.py
