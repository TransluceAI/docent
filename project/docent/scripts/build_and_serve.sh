#!/bin/bash
set -e

# Navigate to the parent directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd $SCRIPT_DIR

# Default values
PORT=3000
HOST="http://localhost:8888"
POSTHOG_KEY="${NEXT_PUBLIC_POSTHOG_KEY:-}"
POSTHOG_HOST="${NEXT_PUBLIC_POSTHOG_HOST:-}"
SKIP_POSTHOG=false

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --port|-p) PORT="$2"; shift ;;
        --host|-h) HOST="$2"; shift ;;
        --skip_posthog) SKIP_POSTHOG=true ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# Validate required environment variables if not skipping PostHog
if [ "$SKIP_POSTHOG" = false ]; then
    if [ -z "$POSTHOG_KEY" ]; then
        echo "Error: NEXT_PUBLIC_POSTHOG_KEY environment variable is not set"
        exit 1
    fi

    if [ -z "$POSTHOG_HOST" ]; then
        echo "Error: NEXT_PUBLIC_POSTHOG_HOST environment variable is not set"
        exit 1
    fi
fi

# Check if node_modules exists and run npm install if needed
cd web
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Run Next.js with environment variables
NEXT_PUBLIC_API_HOST=$HOST \
NEXT_PUBLIC_POSTHOG_KEY=$POSTHOG_KEY \
NEXT_PUBLIC_POSTHOG_HOST=$POSTHOG_HOST \
npm run build

npm run start -- --port $PORT
