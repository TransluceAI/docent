#!/bin/bash
set -e

# Navigate to the parent directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd $SCRIPT_DIR

# Lock the requirements for Read the Docs
uv export --extra dev --no-editable --no-hashes --format requirements-txt > docs/requirements-locked.txt
