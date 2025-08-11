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

NUM_WORKERS=${NUM_WORKERS:-2}
echo "NUM_WORKERS: ${NUM_WORKERS}"

# Use os_environ to allow overriding .env via TF
if [ "$SERVICE" == "server" ]; then
  echo "Starting server on port 8000 with ${NUM_WORKERS} worker(s)"
  ENV_RESOLUTION_STRATEGY=os_environ docent_core server --port 8000 --workers ${NUM_WORKERS} --no-start-docent-worker
elif [ "$SERVICE" == "worker" ]; then
  echo "Starting ${NUM_WORKERS} worker(s)"

  # Ensure child processes are terminated on container stop
  pids=()
  term_children() {
    echo "Stopping workers"
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill -TERM "$pid" >/dev/null 2>&1 || true
      fi
    done
    wait
  }
  trap term_children SIGINT SIGTERM

  # Start workers in background; all log to stdout
  for i in $(seq 1 "$NUM_WORKERS"); do
    echo "Starting worker $i"
    ENV_RESOLUTION_STRATEGY=os_environ WORKER_ID="$i" docent_core worker &
    pids+=("$!")
  done

  # Wait for all workers
  wait
fi
