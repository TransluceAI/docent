#!/bin/bash

set -euo pipefail

WORKERS=("datadog-agent" "telemetry-ingest-worker" "telemetry-processing-worker" "worker")

show_help() {
    cat <<EOF
Usage: $0 <deployment-id> [worker...] [-f|--filter-pattern <pattern>] [-s|--since <time>]

Watch the shared ECS log group for a deployment and filter logs by worker
prefixes using the log stream name prefix. Defaults to all workers. Any extra
filter pattern provided is passed directly to each tail command.

Options:
  -f, --filter-pattern  CloudWatch Logs filter pattern
  -s, --since           How far back to start (default: 30m)

Workers:
  datadog-agent
  telemetry-ingest-worker
  telemetry-processing-worker
  worker

Examples:
  $0 bwater                                   # follow all workers
  $0 bwater worker                            # follow only the main worker
  $0 bwater worker telemetry-ingest-worker -f '"ERROR"'
  $0 --list                                   # show worker names
EOF
}

list_workers() {
    echo "Available workers:"
    for w in "${WORKERS[@]}"; do
        echo "  - $w"
    done
}

DEPLOYMENT_ID=""
USER_FILTER=""
SINCE="30m"
WORKER_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        --list)
            list_workers
            exit 0
            ;;
        -f|--filter-pattern)
            shift
            if [[ $# -eq 0 ]]; then
                echo "Missing filter pattern after -f|--filter-pattern" >&2
                exit 1
            fi
            USER_FILTER=$1
            shift
            ;;
        -s|--since)
            shift
            if [[ $# -eq 0 ]]; then
                echo "Missing time after -s|--since" >&2
                exit 1
            fi
            SINCE=$1
            shift
            ;;
        *)
            if [[ -z "$DEPLOYMENT_ID" ]]; then
                DEPLOYMENT_ID=$1
            else
                WORKER_ARGS+=("$1")
            fi
            shift
            ;;
    esac
done

if [[ -z "$DEPLOYMENT_ID" ]]; then
    show_help
    exit 1
fi

SELECTED_WORKERS=()
if [[ ${#WORKER_ARGS[@]} -gt 0 ]]; then
    SELECTED_WORKERS=("${WORKER_ARGS[@]}")
else
    SELECTED_WORKERS=("${WORKERS[@]}")
fi

for worker in "${SELECTED_WORKERS[@]}"; do
    found=false
    for w in "${WORKERS[@]}"; do
        if [[ "$worker" == "$w" ]]; then
            found=true
            break
        fi
    done
    if [[ "$found" == false ]]; then
        echo "Unknown worker: $worker" >&2
        echo "Use --list to see available workers." >&2
        exit 1
    fi
done

LOG_GROUP="/ecs/docent-${DEPLOYMENT_ID}"

PREFIXES=()
for w in "${SELECTED_WORKERS[@]}"; do
    PREFIXES+=("${w}")  # NOTE(mengk): kind of weird, but it works I guess
done

PIDS=()
cleanup() {
    if [[ ${#PIDS[@]} -gt 0 ]]; then
        echo "Stopping log tails..." >&2
        kill "${PIDS[@]}" 2>/dev/null || true
        wait "${PIDS[@]}" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

for prefix in "${PREFIXES[@]}"; do
    CMD=(aws logs tail "${LOG_GROUP}" --log-stream-name-prefix "${prefix}" --follow --since="$SINCE")
    if [[ -n "$USER_FILTER" ]]; then
        CMD+=(--filter-pattern "${USER_FILTER}")
    fi

    echo "Running: ${CMD[*]}"
    "${CMD[@]}" &
    PIDS+=($!)
done

if [[ ${#PIDS[@]} -eq 0 ]]; then
    echo "No log tails started; check worker selection." >&2
    exit 1
fi

wait "${PIDS[@]}"
