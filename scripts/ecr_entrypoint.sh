#!/bin/bash
set -e

# We use $SERVICE to modulate between server and worker
if [ -z "$SERVICE" ]; then
  echo "Error: SERVICE environment variable is not set."
  exit 1
fi
if [ "$SERVICE" != "server" ] && [ "$SERVICE" != "worker" ]; then
  echo "Error: SERVICE must be either 'server' or 'worker'."
  exit 1
fi

# Use os_environ to allow overriding .env via TF
if [ "$SERVICE" == "server" ]; then
  # Port 8000 and 1 worker is default for AppRunner
  echo "Starting server on port 8000 with 1 worker"
  ENV_RESOLUTION_STRATEGY=os_environ docent_core server --port 8000 --workers 1 --no-start-docent-worker
elif [ "$SERVICE" == "worker" ]; then
  echo "Starting worker"
  ENV_RESOLUTION_STRATEGY=os_environ docent_core worker
fi
