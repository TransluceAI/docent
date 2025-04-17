#!/bin/bash
set -e

# Navigate to the parent directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd $SCRIPT_DIR

# Navigate to project root
cd ../../

# Assert current branch is docent-share
if [ "$(git branch --show-current)" != "docent-share" ]; then
    echo "Current branch is not docent-share"
    exit 1
fi

# Sync
git branch -D docent-share-compress || true
git checkout --orphan docent-share-compress
git add -A
git commit -m "Sync" --no-verify
# Add remote if it doesn't exist already
if ! git remote | grep -q "^docent-remote$"; then
  git remote add docent-remote https://github.com/TransluceAI/docent.git
fi
git push --force docent-remote docent-share-compress:main
