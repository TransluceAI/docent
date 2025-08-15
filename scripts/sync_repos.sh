#!/bin/bash
set -e

# Navigate to the parent directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd $SCRIPT_DIR

# Directory to apply special cleanup rules
SPECIAL_CLEANUP_DIR="docent_core"

# Assert current branch is main
if [ "$(git branch --show-current)" != "main" ]; then
    echo "Current branch is not main"
    exit 1
fi

# Add remote if it doesn't exist already
if ! git remote | grep -q "^docent-public$"; then
  git remote add docent-public https://github.com/TransluceAI/docent.git
fi

# Fetch the latest changes from the docent-public remote
git fetch docent-public

# Check if docent-public-sync branch exists, if so delete it
if git branch | grep -q "docent-public-sync"; then
    git branch -D docent-public-sync
fi

# Create a new branch tracking the remote docent-public main
git checkout -b docent-public-sync docent-public/main

# Copy files from main branch, excluding specified folders
echo "Syncing files from main branch (excluding: .aws, .github, data, personal, scripts)..."

# Remove all current files except .git
find . -maxdepth 1 -not -name '.git' -not -name '.' -exec rm -rf {} +

# Copy files from main branch, excluding the specified folders
git checkout main -- .
rm -rf .aws .github data personal scripts

# Special handling for special cleanup directory
if [ -d "$SPECIAL_CLEANUP_DIR" ]; then
    echo "Cleaning up $SPECIAL_CLEANUP_DIR directory..."
    cd "$SPECIAL_CLEANUP_DIR"

    # Remove README.md if it exists
    if [ -f "README.md" ]; then
        rm README.md
    fi

    # Remove directories that don't start with underscore and aren't named 'docent'
    for dir in */; do
        if [ -d "$dir" ]; then
            dirname=$(basename "$dir")
            # Keep directories starting with underscore or named 'docent'
            if [[ "$dirname" != _* ]] && [[ "$dirname" != "docent" ]]; then
                echo "Removing directory: $SPECIAL_CLEANUP_DIR/$dirname"
                rm -rf "$dir"
            fi
        fi
    done

    cd ..
fi

# Stage all changes
git add -A

# Check if there are any changes to commit
if git diff --staged --quiet; then
    echo "No changes to sync"
    git checkout main
    git branch -D docent-public-sync
else
    # Commit the changes
    git commit -m "Update $(date +%Y-%m-%d)" --no-verify

    # Push to docent-public main branch
    git push docent-public docent-public-sync:main

    echo "Changes synced and pushed to docent-public repository"

    # Return to main branch and clean up
    git checkout main
    git branch -D docent-public-sync
fi

echo "Sync complete"
