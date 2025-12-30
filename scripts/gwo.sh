#!/bin/bash
set -e

# Navigate to project root directory
ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd "$ROOT_DIR"

# Select and switch to a git worktree using gum.
# Worktrees are sorted by recency (most recently accessed first).

# Navigate to project root directory (or any git directory)
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  echo "Not in a git repository" >&2
  exit 1
fi

# Get list of worktrees
worktrees=$(git worktree list --porcelain | grep "^worktree " | sed 's/^worktree //')

if [[ -z "$worktrees" ]]; then
  echo "No worktrees found" >&2
  exit 1
fi

# Sort worktrees by access time (most recent first)
sorted_worktrees=$(echo "$worktrees" | while read -r path; do
  if [[ -d "$path" ]]; then
    # Get access time in seconds since epoch
    atime=$(stat -f "%a" "$path" 2>/dev/null || stat -c "%X" "$path" 2>/dev/null || echo "0")
    echo "$atime $path"
  fi
done | sort -rn | cut -d' ' -f2-)

if [[ -z "$sorted_worktrees" ]]; then
  echo "No accessible worktrees found" >&2
  exit 1
fi

# Use gum to select a worktree
selected=$(echo "$sorted_worktrees" | gum choose --header "Select a worktree:")

if [[ -z "$selected" ]]; then
  # User cancelled, stay in current directory
  echo "."
  exit 0
fi

# Print the selected path so caller can cd to it: cd $(gwo.sh)
echo "$selected"
