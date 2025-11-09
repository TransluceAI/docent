#!/bin/bash
set -e

# Determine the parent directory of this script
ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"

# Parse arguments
TARGET_BRANCH=""
SOURCE_BRANCH="main"

while [[ "$#" -gt 0 ]]; do
  case $1 in
    -t|--target)
      TARGET_BRANCH="$2"
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

# Validate target branch
if [ -z "$TARGET_BRANCH" ]; then
  error "You must specify a target branch with -t or --target"
  exit 1
fi

###############################
# Tag HEAD if pushing to prod #
###############################

if [ "$TARGET_BRANCH" != "staging" ]; then
  echo "Since you're pushing to a non-staging branch, let's tag HEAD with a version bump."
  . $ROOT_DIR/scripts/bump_version.sh
  # The script will not continue if tag creation fails
fi

################################
# Force push the target branch #
################################

# Confirmation prompt - this is a destructive operation
read -p "⚠️ Type 'FORCE PUSH' to confirm that you want to overwrite '$TARGET_BRANCH' with the contents of '$SOURCE_BRANCH': " confirmation

if [ "$confirmation" != "FORCE PUSH" ]; then
  echo "Operation cancelled. Confirmation text did not match."
  exit 1
fi

# Require exact branch name confirmation as an additional safeguard
read -p "Now type the source branch name exactly to proceed: " source_confirmation
if [ "$source_confirmation" != "$SOURCE_BRANCH" ]; then
  echo "Operation cancelled. Source branch name did not match."
  exit 1
fi

# Require target branch confirmation as well
read -p "Finally, type the target branch name exactly to proceed: " branch_confirmation
if [ "$branch_confirmation" != "$TARGET_BRANCH" ]; then
  echo "Operation cancelled. Target branch name did not match."
  exit 1
fi

echo "Proceeding with force push operation..."

# Sync branches
git checkout $SOURCE_BRANCH
git pull origin $SOURCE_BRANCH
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
