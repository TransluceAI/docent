#!/bin/bash
set -e

# Navigate to the parent directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd $SCRIPT_DIR

# Default values
PORT=3000
HOST="http://localhost:8888"

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --port|-p) PORT="$2"; shift ;;
        --host|-h) HOST="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# Check if node_modules exists and run npm install if needed
cd web
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Run Next.js with environment variables
NEXT_PUBLIC_API_HOST=$HOST npm run dev -- --port $PORT
