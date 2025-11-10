#!/bin/bash

# Check if deployment id is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <deployment-id>"
    exit 1
fi

DEPLOYMENT_ID=$1

aws logs tail /ecs/docent-${DEPLOYMENT_ID} --follow --since=1h
