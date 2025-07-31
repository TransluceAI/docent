#!/bin/bash
echo "Switching to bridgewater environment..."
if terraform init -backend-config=bridgewater.hcl -reconfigure; then
    echo "Ready to apply bridgewater environment with: terraform plan -var-file=bridgewater.tfvars"
else
    echo "Error: Failed to switch to bridgewater environment. Please check your configuration."
    exit 1
fi
