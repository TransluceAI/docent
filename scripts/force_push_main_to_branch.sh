#!/bin/bash
set -e

# Parse arguments
BRANCH=""

while [[ "$#" -gt 0 ]]; do
  case $1 in
    -b|--branch)
      BRANCH="$2"
      shift 2
      ;;
    *)
      echo "Unknown parameter passed: $1"
      exit 1
      ;;
  esac
done

if [ -z "$BRANCH" ]; then
  echo "Error: You must specify a branch with -b or --branch"
  exit 1
fi

# Sync branches
git checkout main
git pull origin main
git checkout $BRANCH
git pull origin $BRANCH

# Create a backup branch with a timestamp
BACKUP_BRANCH="${BRANCH}-backup-$(date +%Y%m%d%H%M%S)"
git checkout -b "$BACKUP_BRANCH"
git push origin "$BACKUP_BRANCH"

# Reset branch to match main
git checkout $BRANCH
git reset --hard main

# Force push branch to remote
git push origin $BRANCH --force
