#!/bin/bash
echo "Switching to app environment..."
if terraform init -backend-config=app.hcl -reconfigure; then
    echo "Ready to apply app environment with: terraform plan -var-file=app.tfvars"
else
    echo "Error: Failed to switch to app environment. Please check your configuration."
    exit 1
fi
