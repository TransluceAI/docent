#!/bin/bash
echo "Switching to staging environment..."
if terraform init -backend-config=staging.hcl -reconfigure; then
    echo "Ready to apply staging environment with: terraform plan -var-file=staging.tfvars"
else
    echo "Error: Failed to switch to staging environment. Please check your configuration."
    exit 1
fi
