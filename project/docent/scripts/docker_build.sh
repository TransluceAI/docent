#!/bin/bash
set -e

# Default port values
API_PORT=8888
WEB_PORT=3000
ENV_TYPE=prod

# Parse command line arguments
while getopts "a:w:e:" opt; do
  case $opt in
    a) API_PORT=$OPTARG ;;
    w) WEB_PORT=$OPTARG ;;
    e) ENV_TYPE=$OPTARG ;;
    \?) echo "Invalid option: -$OPTARG" >&2; exit 1 ;;
  esac
done

# Navigate to the parent directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd $SCRIPT_DIR

# Go to project root
cd ../../

# Build with Docker and pass port values as build arguments
docker build \
  --build-arg API_PORT=$API_PORT \
  --build-arg WEB_PORT=$WEB_PORT \
  --build-arg ENV_TYPE=$ENV_TYPE \
  -t docent-preview \
  -f project/docent/Dockerfile .

echo "Docker image built with API port: $API_PORT and Web port: $WEB_PORT"
