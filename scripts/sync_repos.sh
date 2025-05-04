#!/bin/bash
set -e

# Navigate to the parent directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd $SCRIPT_DIR

# Assert current branch is docent-sync-2
if [ "$(git branch --show-current)" != "docent-sync-2" ]; then
    echo "Current branch is not docent-sync-2"
    exit 1
fi

# Add remote if it doesn't exist already
if ! git remote | grep -q "^docent-remote$"; then
  git remote add docent-remote https://github.com/TransluceAI/docent.git
fi

# Fetch the latest changes from the remote
git fetch docent-remote

# Check if docent-sync-2-compress branch exists
if git branch | grep -q "docent-sync-2-compress"; then
    # Checkout to existing branch
    git checkout docent-sync-2-compress
    # Make sure it's up to date with remote main
    git reset --hard docent-remote/main
else
    # Create a new branch tracking the remote
    git checkout -b docent-sync-2-compress docent-remote/main
fi

# Apply changes from docent-sync-2 to docent-sync-2-compress
# Empty the index/work-tree (this stages deletions)
git rm -r --cached .     # tracked files
git clean -fdx           # untracked junk; optional but nice
# Populate with docent-sync-2’s snapshot
git checkout docent-sync-2 -- .
# Stage and commit
git add -A
git commit -m "Sync changes from docent-sync-2 $(date +%Y-%m-%d)" --no-verify || echo "No changes to commit"

# Create a timestamp branch name with milliseconds to avoid conflicts
TIMESTAMP_BRANCH="sync-$(date +%Y%m%d-%H%M%S.%3N)"
echo "Creating branch: $TIMESTAMP_BRANCH"

# Push the changes to remote with the timestamped branch instead of main
git push docent-remote docent-sync-2-compress:$TIMESTAMP_BRANCH

echo "Changes pushed to branch: $TIMESTAMP_BRANCH on remote repository"
