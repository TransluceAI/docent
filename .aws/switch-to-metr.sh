#!/bin/bash
echo "Switching to metr environment..."
if terraform init -backend-config=metr.hcl -reconfigure; then
    echo "Ready to apply metr environment with: terraform plan -var-file=metr.tfvars"
else
    echo "Error: Failed to switch to metr environment. Please check your configuration."
    exit 1
fi
