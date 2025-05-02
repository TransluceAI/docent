#!/bin/bash

# Determine which shell config file to use
SHELL_CONFIG=""
if [[ "$SHELL" == *"zsh"* ]]; then
  SHELL_CONFIG="$HOME_DIR/.zshrc"
else
  SHELL_CONFIG="$HOME_DIR/.bashrc"
fi
echo "Detected shell: $SHELL_CONFIG"

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $SHELL_CONFIG

# Check if .env file exists
if [ ! -f "$TRANSLUCE_HOME/.env" ]; then
  echo "Error: $TRANSLUCE_HOME/.env file not found. Please create a .env file before building."
  return 1
fi

# Install Docent into the current venv
uv sync

# Download sample logs
# SAMPLE_LOGS_DIR="$TRANSLUCE_HOME/../sample-transcripts"
# EVAL_LOGS_DIR="$SAMPLE_LOGS_DIR/raw"
# git clone https://github.com/TransluceAI/sample-transcripts.git $SAMPLE_LOGS_DIR || { echo "Failed to clone sample transcripts"; return 1; }
# python3 $SAMPLE_LOGS_DIR/unzip.py || { echo "Failed to unzip sample transcripts"; return 1; }
