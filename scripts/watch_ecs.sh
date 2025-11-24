#!/bin/bash

set -euo pipefail

WORKERS=("datadog-agent" "telemetry-ingest-worker" "telemetry-processing-worker" "worker")

show_help() {
    cat <<EOF
Usage: $0 <deployment-id> [worker...]

Watch the shared ECS log group for a deployment and filter logs by worker
prefixes using grep. Defaults to all workers.

Workers:
  datadog-agent
  telemetry-ingest-worker
  telemetry-processing-worker
  worker

Examples:
  $0 bwater                         # follow all workers
  $0 bwater worker                  # follow only the main worker
  $0 bwater worker telemetry-ingest-worker
  $0 --list                         # show worker names
EOF
}

list_workers() {
    echo "Available workers:"
    for w in "${WORKERS[@]}"; do
        echo "  - $w"
    done
}

if [ $# -eq 0 ]; then
    show_help
    exit 1
fi

case "${1:-}" in
    -h|--help)
        show_help
        exit 0
        ;;
    --list)
        list_workers
        exit 0
        ;;
esac

DEPLOYMENT_ID=$1
shift

SELECTED_WORKERS=()
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        --list)
            list_workers
            exit 0
            ;;
        *)
            found=false
            for w in "${WORKERS[@]}"; do
                if [ "$1" = "$w" ]; then
                    found=true
                    SELECTED_WORKERS+=("$w")
                    break
                fi
            done
            if [ "$found" = false ]; then
                echo "Unknown worker: $1"
                echo "Use --list to see available workers."
                exit 1
            fi
            ;;
    esac
    shift
done

if [ ${#SELECTED_WORKERS[@]} -eq 0 ]; then
    SELECTED_WORKERS=("${WORKERS[@]}")
fi

LOG_GROUP="/ecs/docent-${DEPLOYMENT_ID}"
echo "Log group: ${LOG_GROUP}"
echo "Filtering workers: ${SELECTED_WORKERS[*]}"

PREFIXES=()
for w in "${SELECTED_WORKERS[@]}"; do
    PREFIXES+=("${w}/${w}/")  # NOTE(mengk): kind of weird, but it works I guess
done

GREP_PATTERN=$(printf "|%s" "${PREFIXES[@]}")
GREP_PATTERN=${GREP_PATTERN:1}

aws logs tail "${LOG_GROUP}" --follow --since=30m | grep -E --line-buffered "${GREP_PATTERN}"
