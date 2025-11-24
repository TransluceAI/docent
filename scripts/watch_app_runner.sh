#!/bin/bash

set -euo pipefail

usage() {
    echo "Usage: $0 <deployment-id> [--no-telemetry]"
    exit 1
}

DEPLOYMENT_ID=""
NO_TELEMETRY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-telemetry)
            NO_TELEMETRY=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            if [[ -z "$DEPLOYMENT_ID" ]]; then
                DEPLOYMENT_ID=$1
                shift
            else
                echo "Unexpected argument: $1"
                usage
            fi
            ;;
    esac
done

if [[ -z "$DEPLOYMENT_ID" ]]; then
    usage
fi

FILTER_PATTERN='-"GET / HTTP"'
if $NO_TELEMETRY; then
    FILTER_PATTERN+=' -"telemetry"'
fi

LOG_GROUP=$(aws logs describe-log-groups --log-group-name-prefix /aws/apprunner | jq -r --arg id "$DEPLOYMENT_ID" '.logGroups[] | select(.logGroupName | contains($id) and contains("application")) | .logGroupName')

if [[ -z "$LOG_GROUP" ]]; then
    echo "Could not find an App Runner application log group for deployment id: $DEPLOYMENT_ID" >&2
    exit 1
fi

aws logs tail "$LOG_GROUP" --filter-pattern "$FILTER_PATTERN" --follow --since=30m
