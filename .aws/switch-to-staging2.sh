#!/bin/bash
echo "Switching to staging2  environment..."
if terraform init -backend-config=staging2.hcl -reconfigure; then
    echo "Ready to apply staging2 environment with: terraform plan -var-file=staging2.tfvars"
else
    echo "Error: Failed to switch to staging2 environment. Please check your configuration."
    exit 1
fi
