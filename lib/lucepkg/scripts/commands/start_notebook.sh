#!/bin/bash

# Exit on error
set -e

port="$1"
working_dir="$2"
use_sudo="$3"
monorepo_root="$4"

# Use the specific jupyter from monorepo venv
JUPYTER="$monorepo_root/.venv/bin/jupyter"

# Check if port is already in use
if lsof -i :"$port" > /dev/null 2>&1; then
    echo "Error: Port $port is already in use" >&2
    exit 1
fi

# Check for existing certificate
CERT_DIR="$HOME/.luce/cert"
CERT_PATH="$CERT_DIR/notebook.pem"
KEY_PATH="$CERT_DIR/notebook.key"

if [ ! -f "$CERT_PATH" ] || [ ! -f "$KEY_PATH" ]; then
    # Create cert directory if it doesn't exist
    mkdir -p "$CERT_DIR"

    # Generate self-signed certificate
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$KEY_PATH" \
        -out "$CERT_PATH" \
        -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"

    echo "Generated new self-signed certificate in $CERT_DIR"
fi

"$JUPYTER" notebook --notebook-dir="$working_dir" \
    --allow_origin='*' \
    --ip=0.0.0.0 \
    --port="$port" \
    --certfile="" \
    --keyfile="" \
    --no-browser \
    --allow-root \
    > "jupyter_${port}_log_gitignore.txt" 2>&1 & JUPYTER_PID=$!

# Wait a bit for the server to start
sleep 5
# Get and print the token URL
echo "Jupyter notebook server started with PID: $JUPYTER_PID"
echo "Server logs are being written to: $working_dir/jupyter_${port}_log_gitignore.txt"
"$JUPYTER" server list | grep ":$port/"
