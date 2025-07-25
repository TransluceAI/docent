#!/bin/bash
echo "Switching to prod environment..."
if terraform init -backend-config=prod.hcl -reconfigure; then
    echo "Ready to apply prod environment with: terraform plan -var-file=prod.tfvars"
else
    echo "Error: Failed to switch to prod environment. Please check your configuration."
    exit 1
fi
