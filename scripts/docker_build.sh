#!/bin/bash
set -e

# Default port values
SERVER_PORT=8888
WEB_PORT=3000

# Parse command line arguments
while getopts "a:w:e:" opt; do
  case $opt in
    a) SERVER_PORT=$OPTARG ;;
    w) WEB_PORT=$OPTARG ;;
    \?) echo "Invalid option: -$OPTARG" >&2; exit 1 ;;
  esac
done

# Navigate to the parent directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd $SCRIPT_DIR

# Source .env and collect the Postgres args
source .env
if [ -z "$DOCENT_PG_USER" ]; then
  echo "Error: DOCENT_PG_USER is not set in .env file" >&2
  exit 1
fi

if [ -z "$DOCENT_PG_PASSWORD" ]; then
  echo "Error: DOCENT_PG_PASSWORD is not set in .env file" >&2
  exit 1
fi

if [ -z "$DOCENT_PG_DATABASE" ]; then
  echo "Error: DOCENT_PG_DATABASE is not set in .env file" >&2
  exit 1
fi

# Build with Docker and pass port values as build arguments
docker build \
  --build-arg SERVER_PORT=$SERVER_PORT \
  --build-arg WEB_PORT=$WEB_PORT \
  --build-arg POSTGRES_USER=$DOCENT_PG_USER \
  --build-arg POSTGRES_PASSWORD=$DOCENT_PG_PASSWORD \
  --build-arg POSTGRES_DB=$DOCENT_PG_DATABASE \
  -t docent-preview \
  -f Dockerfile .

echo "Docker image built with API port: $SERVER_PORT and Web port: $WEB_PORT"
