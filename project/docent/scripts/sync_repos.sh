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

# Add remote if it doesn't exist already
if ! git remote | grep -q "^docent-remote$"; then
  git remote add docent-remote https://github.com/TransluceAI/docent.git
fi

# Fetch the latest changes from the remote
git fetch docent-remote

# Check if docent-share-compress branch exists
if git branch | grep -q "docent-share-compress"; then
    # Checkout to existing branch
    git checkout docent-share-compress
    # Make sure it's up to date with remote main
    git reset --hard docent-remote/main
else
    # Create a new branch tracking the remote
    git checkout -b docent-share-compress docent-remote/main
fi

# Apply changes from docent-share to docent-share-compress
git checkout docent-share -- .
git add -A
git commit -m "Sync changes from docent-share $(date +%Y-%m-%d)" --no-verify || echo "No changes to commit"

# Push the changes to remote
git push docent-remote docent-share-compress:main
