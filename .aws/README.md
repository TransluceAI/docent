# Docent AWS Infrastructure

This directory contains Terraform configuration for deploying Docent on AWS.

## Architecture

The infrastructure includes:

- **VPC**: Custom VPC with public and private subnets across 2 AZs
- **RDS**: PostgreSQL 15 database in private subnets
- **ElastiCache**: Redis cluster in private subnets
- **App Runner**: API server (`docent_core/_server/api.py`) with VPC connectivity
- **ECS Fargate**: Worker service (`docent_core/_worker/worker.py`) in private subnets
- **ECR**: Container registries for API and worker images

## Networking

- **Backend (App Runner)** and **Workers (ECS)** can communicate with:
  - Database (RDS) via private subnets
  - Redis (ElastiCache) via private subnets
  - External internet via NAT gateways
- **Backend** is accessible from external internet via App Runner's public endpoint
- **Workers** run in private subnets with no direct internet access

## Prerequisites

1. AWS CLI configured with appropriate credentials
2. Terraform >= 1.0 installed
3. Docker images built and pushed to ECR repositories

## Environment Switching

This setup supports multiple environments (app, staging) with separate state files to prevent conflicts.

### Switching to App Environment
```bash
./switch-to-app.sh
terraform plan -var-file=app.tfvars
terraform apply -var-file=app.tfvars
```

### Switching to Staging Environment
```bash
./switch-to-staging.sh
terraform plan -var-file=staging.tfvars
terraform apply -var-file=staging.tfvars
```

Each environment maintains its own state file in S3, preventing conflicts when switching between environments.

## Deployment

1. Choose your environment and switch to it:
   ```bash
   # For app environment
   ./switch-to-app.sh

   # For staging environment
   ./switch-to-staging.sh
   ```

2. Set database password securely (if not already set in .tfvars):
   ```bash
   # Option 1: Environment variable (recommended)
   export TF_VAR_db_password="your-secure-password"
   ```

3. Plan the deployment:
   ```bash
   # For app environment
   terraform plan -var-file=app.tfvars

   # For staging environment
   terraform plan -var-file=staging.tfvars
   ```

4. Apply the configuration:
   ```bash
   # For app environment
   terraform apply -var-file=app.tfvars

   # For staging environment
   terraform apply -var-file=staging.tfvars
   ```

## Container Images

Before deploying, you need to build and push Docker images:

1. **API Image**: Build from `Dockerfile.backend` and push to the API ECR repository
2. **Worker Image**: Build from `Dockerfile.backend` (same image, different command) and push to the Worker ECR repository

The ECR repository URLs will be output after running `terraform apply`.

## Environment Variables

The infrastructure automatically configures these environment variables:

### API Server (App Runner)
- `DEPLOYMENT_ID`: Used for Sentry environment
- `DOCENT_DATABASE_HOST`: PostgreSQL host endpoint
- `DOCENT_DATABASE_PORT`: PostgreSQL port (5432)
- `DOCENT_DATABASE_NAME`: Database name (docent)
- `DOCENT_REDIS_HOST`: Redis endpoint
- `DOCENT_REDIS_PORT`: Redis port (6379)
- `DOCENT_CORS_ORIGINS`: CORS origins (empty for dev mode)

### Worker (ECS)
- `DOCENT_DATABASE_HOST`: PostgreSQL host endpoint
- `DOCENT_DATABASE_PORT`: PostgreSQL port (5432)
- `DOCENT_DATABASE_NAME`: Database name (docent)
- `DOCENT_REDIS_HOST`: Redis endpoint
- `DOCENT_REDIS_PORT`: Redis port (6379)

**Note**: Database credentials (username/password) must be provided to the application through secure deployment methods outside of Terraform, such as container environment variables or application configuration.

## Security

- All databases and caches are in private subnets
- Security groups restrict access to necessary ports only
- RDS and ElastiCache have encryption at rest and in transit
- ECR repositories scan images for vulnerabilities

## Monitoring

- CloudWatch logs for ECS tasks
- RDS Enhanced Monitoring enabled
- App Runner has built-in monitoring and auto-scaling

## Cleanup

To destroy the infrastructure:

```bash
terraform destroy
```

**Warning**: This will permanently delete all resources including databases. Make sure to backup any important data first.
