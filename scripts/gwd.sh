#!/bin/bash
set -e

# Remove worktree and branch from within active worktree directory.

# Check if we're in a worktree (not the main working tree)
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  echo "Not in a git repository"
  exit 1
fi

# git worktree list --porcelain shows the worktree path; if there's only one entry
# and it matches this directory, we're in the main worktree, not a linked one
main_worktree="$(git worktree list --porcelain | head -1 | sed 's/^worktree //')"
current_dir="$(git rev-parse --show-toplevel)"

if [[ "$main_worktree" == "$current_dir" ]]; then
  echo "Not in a linked worktree (this is the main working tree)"
  exit 1
fi

worktree_path="$current_dir"
worktree="$(basename "$worktree_path")"

# split on first `--`
root="${worktree%%--*}"
# Get the actual branch name from git (handles '/' in branch names correctly)
branch="$(git rev-parse --abbrev-ref HEAD)"

if gum confirm "Remove worktree '$worktree' (branch '$branch')?"; then
  git worktree remove "$worktree_path" --force >&2

  # Print the root path so caller can cd to it: cd $(gwd.sh)
  echo "$(dirname "$worktree_path")/$root"
else
  # "cd" to the current directory if operation cancelled
  echo "."
fi
