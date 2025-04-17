#!/bin/bash

# Function to find monorepo root from script location
__find_monorepo_root() {
    local script_dir
    if [ -n "$ZSH_VERSION" ]; then
        # In zsh, use ${(%):-%x} to get the function's source file
        # see https://stackoverflow.com/a/28336473
        script_dir="$(cd "$(dirname "${(%):-%x}")" && pwd)"
    else  # bash
        script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    fi

    # Verify we're in the expected location
    if [[ "$script_dir" != */lib/lucepkg/scripts ]]; then
        echo "Error: This script must be run from lib/lucepkg/scripts/activate_luce.sh" >&2
        echo "Current location: $script_dir" >&2
        return 1
    fi

    # Get the monorepo root (three directories up from scripts)
    echo "$(cd "$script_dir/../../.." && pwd)"
}

# Find and export monorepo root when script is sourced
if ! MONOREPO_ROOT="$(__find_monorepo_root)"; then
    unset -f __find_monorepo_root
    return 1
fi
export MONOREPO_ROOT
unset -f __find_monorepo_root

luce() {
    # Check if uv is installed
    if ! command -v uv &> /dev/null; then
        # If command is "uv install", install uv
        if [ "$#" -eq 2 ] && [ "$1" = "uv" ] && [ "$2" = "install" ]; then
            echo "Installing uv package installer..."
            curl -LsSf https://astral.sh/uv/install.sh | sh

            # Source the RC file to add UV to PATH:
            echo "Sourcing ~/.local/bin/env"
            source $HOME/.local/bin/env
            return 0
        else
            echo "Error: uv package manager is not installed." >&2
            echo "Please run 'luce uv install' first or install uv manually." >&2
            return 1
        fi
    fi

    local lucepkg_root="$MONOREPO_ROOT/lib/lucepkg"

    # We temporarily unset VIRTUAL_ENV to silence a UV warning, since we are telling UV to run the
    # script in a different virtual environment (see --internal-restore-virtual-env below)
    if [ -n "$LUCE_DISALLOW_SHELL_COMMANDS" ]; then
        # Just run the command without shell integration
        VIRTUAL_ENV="" uv run --project "${lucepkg_root}" python -m lucepkg \
            --internal-restore-virtual-env "$VIRTUAL_ENV" \
            "$@"
        return $?
    fi

    # Create secure temporary directory
    local tmp_dir
    tmp_dir=$(mktemp -d 2>/dev/null || mktemp -d -t 'lucetmp')

    # Ensure temp dir cleanup on exit
    trap 'rm -rf "$tmp_dir"' EXIT

    local shell_commands_file="$tmp_dir/shell_commands"

    # Run the Python CLI with the shell commands file using uv.
    # Again we use --internal-restore-virtual-env to silence a UV warning.
    VIRTUAL_ENV="" uv run --project "${lucepkg_root}" python -m lucepkg \
        --internal-output-shell-commands-to "$shell_commands_file" \
        --internal-restore-virtual-env "$VIRTUAL_ENV" \
        "$@"
    local exit_code=$?

    # If Python command succeeded and shell commands file exists, source it
    if [ $exit_code -eq 0 ] && [ -f "$shell_commands_file" ]; then
        echo "==== Executing commands in your shell: ===="
        cat "$shell_commands_file"
        # shellcheck source=/dev/null
        source "$shell_commands_file"
    fi

    return $exit_code
}

# Make this script available in PATH as well, in case it is executed by a child process rather
# than this shell. Commands that change the shell environment will not run when run from PATH.
export PATH="$PATH:$MONOREPO_ROOT/lib/lucepkg/bin"
