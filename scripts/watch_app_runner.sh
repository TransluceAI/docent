#!/bin/bash

# Check if deployment id is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <deployment-id>"
    exit 1
fi

DEPLOYMENT_ID=$1

aws logs tail $(aws logs describe-log-groups --log-group-name-prefix /aws/apprunner | jq -r '.logGroups[] | select(.logGroupName | contains("'${DEPLOYMENT_ID}'") and contains("application")) | .logGroupName') --filter-pattern '-"GET / HTTP"' --follow --since=1h
