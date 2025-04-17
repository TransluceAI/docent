#!/bin/bash
set -e
# Check for MONOREPO_ROOT environment variable and navigate to it
if [ -z "${MONOREPO_ROOT}" ]; then
    echo "Error: MONOREPO_ROOT environment variable is not set"
    exit 1
fi
cd "${MONOREPO_ROOT}"

# cleanup all environments
sudo .venv/bin/inspect sandbox cleanup docker
