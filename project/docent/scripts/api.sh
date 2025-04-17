#!/bin/bash
set -e
# Check for MONOREPO_ROOT environment variable and navigate to it
if [ -z "${MONOREPO_ROOT}" ]; then
    echo "Error: MONOREPO_ROOT environment variable is not set"
    exit 1
fi
cd "${MONOREPO_ROOT}"

# Default values
PORT=8888
DEV_MODE=false
WORKERS=1

# Parse arguments
while [[ $# -gt 0 ]]
do
    case $1 in
        --port|-p)
        PORT="$2"
        shift 2
        ;;
        --dev|-d)
        DEV_MODE=true
        shift
        ;;
        --workers|-w)
        WORKERS="$2"
        shift 2
        ;;
        *)
        shift
        ;;
    esac
done

# Set up the command
if [ "$DEV_MODE" = true ]; then
    COMMAND=".venv/bin/python3 -m uvicorn docent.server.main:asgi_app --host 0.0.0.0 --loop=asyncio --port $PORT --reload"
else
    COMMAND=".venv/bin/python3 -m uvicorn docent.server.main:asgi_app --host 0.0.0.0 --loop=asyncio --port $PORT --workers $WORKERS"
fi

# Handle Ctrl+C by force killing the specific child process
trap 'echo -e "\nForce stopping server..." && kill -9 $! && exit 0' INT

# Execute the command in background and save its PID
$COMMAND & wait $!
