#!/bin/bash
set -e

# Navigate to project root directory
ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd "$ROOT_DIR"

# Create a new worktree and branch from within current git directory.

# Parse options
existing=false
while getopts "e" opt; do
  case $opt in
    e) existing=true ;;
  esac
done
shift $((OPTIND-1))

if [[ -z "$1" ]]; then
  echo "Usage: gwa.sh [-e] [branch name]" >&2
  echo "  -e  Use existing branch instead of creating new" >&2
  exit 1
fi

branch="$1"
base="$(basename "$ROOT_DIR")"
# Replace '/' with '--' in branch name to avoid nested folder structure
safe_branch="${branch//\//-}"
# Use absolute path based on project root's parent directory
path="$(dirname "$ROOT_DIR")/${base}--${safe_branch}"

if $existing; then
  git worktree add "$path" "$branch" >&2
else
  git worktree add -b "$branch" "$path" >&2
fi

# Copy .env file to new worktree if it exists
if [[ -f ".env" ]]; then
  cp ".env" "$path/.env"
  echo "Copied .env file to $path/.env" >&2
fi

# Install dependencies in the new worktree
echo "Running uv sync --extra dev in $path..." >&2
(cd "$path" && uv sync --extra dev) >&2

# Print the path so caller can cd to it: cd $(gwa.sh branch)
echo "$path"
