#!/bin/bash

# Initialize with defaults
TRANSLUCE_HOME="$HOME/clarity"
HOME_DIR=$HOME

# Parse custom home arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --transluce_home|-t) TRANSLUCE_HOME="$2"; shift ;;
        --home_dir|-h) HOME_DIR="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; return 1 ;;
    esac
    shift
done

# Check if .env file exists
if [ ! -f "$TRANSLUCE_HOME/.env" ]; then
  echo "Error: $TRANSLUCE_HOME/.env file not found. Please create a .env file before building."
  return 1
fi

echo "Setting up with TRANSLUCE_HOME=$TRANSLUCE_HOME and HOME_DIR=$HOME_DIR"

# Install luce into ~/.bashrc
echo "export TRANSLUCE_HOME=$TRANSLUCE_HOME" >> $HOME_DIR/.bashrc
echo "source \$TRANSLUCE_HOME/lib/lucepkg/scripts/activate_luce.sh" >> $HOME_DIR/.bashrc
source $HOME_DIR/.bashrc

# Install uv and node
luce uv install || { echo "Failed to install uv"; return 1; }
luce node install -v 22 || { echo "Failed to install node"; return 1; }
source $HOME_DIR/.bashrc

# Install Docent into luce
luce install || { echo "Failed to install luce"; return 1; }
luce activate || { echo "Failed to activate luce"; return 1; }
luce install docent || { echo "Failed to install docent"; return 1; }

# Download sample logs
SAMPLE_LOGS_DIR="$TRANSLUCE_HOME/../sample-transcripts"
EVAL_LOGS_DIR="$SAMPLE_LOGS_DIR/raw"
git clone https://github.com/TransluceAI/sample-transcripts.git $SAMPLE_LOGS_DIR || { echo "Failed to clone sample transcripts"; return 1; }
python3 $SAMPLE_LOGS_DIR/unzip.py || { echo "Failed to unzip sample transcripts"; return 1; }

# Update EVAL_LOGS_DIR in .env file if it exists
sed -i "/^EVAL_LOGS_DIR=/d" $TRANSLUCE_HOME/.env || { echo "Failed to update .env file"; return 1; }
echo "EVAL_LOGS_DIR=$EVAL_LOGS_DIR" >> $TRANSLUCE_HOME/.env || { echo "Failed to update .env file"; return 1; }
