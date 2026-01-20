#!/bin/bash
set -e

# Determine the parent directory of this script
ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"

# Save the current ref so we can restore it at the end of the script.
ORIGINAL_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
ORIGINAL_COMMIT="$(git rev-parse HEAD)"

# Parse arguments
TARGET_BRANCHES=""
SOURCE_BRANCH="main"

while [[ "$#" -gt 0 ]]; do
  case $1 in
    -t|--target)
      TARGET_BRANCHES="$2"
      shift 2
      ;;
    -s|--source)
      SOURCE_BRANCH="$2"
      shift 2
      ;;
    *)
      echo "Unknown parameter passed: $1"
      exit 1
      ;;
  esac
done

# Validate target branches
if [ -z "$TARGET_BRANCHES" ]; then
  echo "You must specify target branch(es) with -t or --target (comma-separated for multiple)"
  exit 1
fi

# Convert comma-separated string to array
IFS=',' read -ra TARGET_ARRAY <<< "$TARGET_BRANCHES"

###############################
# Tag HEAD if pushing to prod #
###############################

# Check if any target branch is not staging (i.e., pushing to prod)
NEEDS_TAG=false
for TARGET_BRANCH in "${TARGET_ARRAY[@]}"; do
  if [ "$TARGET_BRANCH" != "staging" ]; then
    NEEDS_TAG=true
    break
  fi
done

if [ "$NEEDS_TAG" = true ]; then
  echo "Since you're pushing to a non-staging branch, let's tag HEAD with a version bump."
  . $ROOT_DIR/scripts/bump_version.sh
  # The script will not continue if tag creation fails
fi

################################
# Force push the target branch #
################################

# Require exact branch name confirmation as an additional safeguard
read -p "Now type the source branch name exactly to proceed: " source_confirmation
if [ "$source_confirmation" != "$SOURCE_BRANCH" ]; then
  echo "Operation cancelled. Source branch name did not match."
  exit 1
fi

# Require target branches confirmation as well
read -p "Finally, type the target branch(es) exactly to proceed: " branch_confirmation
if [ "$branch_confirmation" != "$TARGET_BRANCHES" ]; then
  echo "Operation cancelled. Target branch(es) did not match."
  exit 1
fi

echo "Proceeding with force push operation..."

# Sync source branch once
git checkout $SOURCE_BRANCH
git pull origin $SOURCE_BRANCH

# Process each target branch
for TARGET_BRANCH in "${TARGET_ARRAY[@]}"; do
  echo ""
  echo "=== Processing target branch: $TARGET_BRANCH ==="

  git checkout $TARGET_BRANCH
  git pull origin $TARGET_BRANCH

  # Create a backup branch with a timestamp
  BACKUP_BRANCH="${TARGET_BRANCH}-backup-$(date +%Y%m%d%H%M%S)"
  git checkout -b "$BACKUP_BRANCH"
  git push origin "$BACKUP_BRANCH"

  # Reset branch to match source
  git checkout $TARGET_BRANCH
  git reset --hard $SOURCE_BRANCH

  # Force push branch to remote
  git push origin $TARGET_BRANCH --force

  echo "=== Completed: $TARGET_BRANCH ==="
done

if [ "$ORIGINAL_BRANCH" = "HEAD" ]; then
  echo "Switching back to the previously active commit: $ORIGINAL_COMMIT"
  git checkout --detach "$ORIGINAL_COMMIT"
else
  echo "Switching back to the previously active branch: $ORIGINAL_BRANCH"
  git checkout "$ORIGINAL_BRANCH"
fi
