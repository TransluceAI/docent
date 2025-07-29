#!/bin/bash
set -e

# Navigate to the parent directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd $SCRIPT_DIR

# Check required environment variables
if [ -z "$PROJECT_NAME" ]; then
  echo "Error: PROJECT_NAME environment variable is not set."
  exit 1
fi
if [ -z "$ENVIRONMENT" ]; then
  echo "Error: ENVIRONMENT environment variable is not set."
  exit 1
fi
if [ -z "$AWS_ACCOUNT_ID" ]; then
  echo "Error: AWS_ACCOUNT_ID environment variable is not set."
  exit 1
fi
if [ -z "$AWS_REGION" ]; then
  echo "Error: AWS_REGION environment variable is not set."
  exit 1
fi

# Construct ECR repository URL
ECR_REPO_URL="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$PROJECT_NAME/$ENVIRONMENT/backend"
echo "Building and pushing to: $ECR_REPO_URL"

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Build the Docker image using Dockerfile.backend for x86_64 platform (AWS App Runner)
docker build --platform linux/amd64 -f Dockerfile.backend -t $PROJECT_NAME-$ENVIRONMENT-backend .

# Tag the image for ECR
docker tag $PROJECT_NAME-$ENVIRONMENT-backend:latest $ECR_REPO_URL:latest

# Push the image to ECR
docker push $ECR_REPO_URL:latest
