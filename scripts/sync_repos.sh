#!/bin/bash
set -e

# Navigate to the parent directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd $SCRIPT_DIR

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

# Give the operator a chance to inspect the working tree before staging
git status --short
while true; do
    read -r -p "Please review the changes above, as well as the state of our working tree. Proceed with syncing? (y/n): " approve
    case "$approve" in
        [Yy])
            break
            ;;
        [Nn])
            echo "Sync aborted by operator"
            git reset --hard
            git checkout main
            git branch -D docent-public-sync
            exit 0
            ;;
        *)
            echo "Please enter y or n"
            ;;
    esac
done

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
