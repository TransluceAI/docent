#!/bin/bash
# Syncs the docent plugin from agent-tools to the claude-code-plugins-internal marketplace repository
#
# The docent plugin contains two skills:
#   - analysis: Analyzing agent behavior with Docent (SKILL.md lives at agent-tools/SKILL.md)
#   - ingestion: Structured workflow for ingesting agent run data into Docent
#
# Usage:
#   ./scripts/sync-plugin-to-marketplace.sh [--commit] [--push]
#
# Options:
#   --commit    Create a git commit in the target repo after syncing
#   --push      Push the commit to origin (implies --commit)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCENT_PLATFORM_ROOT="$(dirname "$SCRIPT_DIR")"
PLUGINS_REPO="${DOCENT_PLATFORM_ROOT}/../claude-code-plugins-internal"

SOURCE_PLUGIN="${DOCENT_PLATFORM_ROOT}/agent-tools/docent"
TARGET_PLUGIN="${PLUGINS_REPO}/plugins/docent"

# The analysis skill SKILL.md lives at the root of agent-tools
ANALYSIS_SKILL_SOURCE="${DOCENT_PLATFORM_ROOT}/agent-tools/SKILL.md"
ANALYSIS_SKILL_TARGET="${TARGET_PLUGIN}/skills/analysis/SKILL.md"

# Parse arguments
DO_COMMIT=false
DO_PUSH=false

for arg in "$@"; do
    case $arg in
        --commit)
            DO_COMMIT=true
            ;;
        --push)
            DO_COMMIT=true
            DO_PUSH=true
            ;;
    esac
done

# Validate paths
if [ ! -d "$SOURCE_PLUGIN" ]; then
    echo "Error: Source plugin not found at $SOURCE_PLUGIN"
    exit 1
fi

if [ ! -d "$PLUGINS_REPO" ]; then
    echo "Error: Plugins repository not found at $PLUGINS_REPO"
    exit 1
fi

if [ ! -f "$ANALYSIS_SKILL_SOURCE" ]; then
    echo "Error: Analysis SKILL.md not found at $ANALYSIS_SKILL_SOURCE"
    exit 1
fi

echo "Syncing docent plugin to marketplace..."
echo "  Source: $SOURCE_PLUGIN"
echo "  Target: $TARGET_PLUGIN"

# Create target directory structure
mkdir -p "$TARGET_PLUGIN"

# Sync the plugin files using rsync
# --delete ensures removed files are also removed in target
rsync -av --delete \
    --exclude='.DS_Store' \
    "$SOURCE_PLUGIN/" "$TARGET_PLUGIN/"

# Copy the analysis skill SKILL.md from agent-tools root
echo "Copying analysis SKILL.md..."
mkdir -p "$(dirname "$ANALYSIS_SKILL_TARGET")"
cp "$ANALYSIS_SKILL_SOURCE" "$ANALYSIS_SKILL_TARGET"

echo "Sync complete!"

# Git operations
if [ "$DO_COMMIT" = true ]; then
    cd "$PLUGINS_REPO"

    # Check if there are changes
    if git diff --quiet && git diff --cached --quiet; then
        echo "No changes to commit."
    else
        git add -A

        # Get the source commit hash for reference
        SOURCE_COMMIT=$(cd "$DOCENT_PLATFORM_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")

        git commit -m "Sync docent plugin from docent-platform

Skills included:
- analysis
- ingestion

Source commit: $SOURCE_COMMIT"

        echo "Created commit in plugins repository."

        if [ "$DO_PUSH" = true ]; then
            git push origin
            echo "Pushed to origin."
        fi
    fi
fi

echo "Done!"
