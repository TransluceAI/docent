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

## Deployment

1. Copy the example variables file:
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```

2. Set database password securely:
   ```bash
   # Option 1: Environment variable (recommended)
   export TF_VAR_db_password="your-secure-password"

   # Option 2: Add to terraform.tfvars (less secure)
   echo 'db_password = "your-secure-password"' >> terraform.tfvars
   ```

3. Edit `terraform.tfvars` with other configuration:
   ```bash
   # Optional: Adjust settings as needed
   aws_region = "us-east-1"
   environment = "dev"
   ```

3. Initialize Terraform:
   ```bash
   terraform init
   ```

4. Plan the deployment:
   ```bash
   terraform plan
   ```

5. Apply the configuration:
   ```bash
   terraform apply
   ```

## Container Images

Before deploying, you need to build and push Docker images:

1. **API Image**: Build from `Dockerfile.backend` and push to the API ECR repository
2. **Worker Image**: Build from `Dockerfile.backend` (same image, different command) and push to the Worker ECR repository

The ECR repository URLs will be output after running `terraform apply`.

## Environment Variables

The infrastructure automatically configures these environment variables:

### API Server (App Runner)
- `ENVIRONMENT`: Environment name (dev/staging/prod)
- `DOCENT_DATABASE_HOST`: PostgreSQL host endpoint
- `DOCENT_DATABASE_PORT`: PostgreSQL port (5432)
- `DOCENT_DATABASE_NAME`: Database name (docent)
- `DOCENT_REDIS_HOST`: Redis endpoint
- `DOCENT_REDIS_PORT`: Redis port (6379)
- `DOCENT_CORS_ORIGINS`: CORS origins (empty for dev mode)

### Worker (ECS)
- `ENVIRONMENT`: Environment name
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
