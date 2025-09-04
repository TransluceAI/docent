#!/bin/bash
set -e

# Navigate to the parent directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd $SCRIPT_DIR

# Check if PYPI_TOKEN is set
if [ -z "$PYPI_TOKEN" ]; then
    echo "Error: PYPI_TOKEN environment variable is not set"
    exit 1
fi

# Build the package
cd docent
if [ -d "dist" ]; then
    rm -r dist
fi
uv build

# Upload the package to PyPI
uv publish --token $PYPI_TOKEN
