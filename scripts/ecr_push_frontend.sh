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
if [ -z "$DEPLOYMENT_ID" ]; then
  echo "Error: DEPLOYMENT_ID environment variable is not set."
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
ECR_REPO_URL="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$PROJECT_NAME/$DEPLOYMENT_ID/frontend"
echo "Building and pushing to: $ECR_REPO_URL"

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Set API host for the build
if [ -z "$NEXT_PUBLIC_API_HOST" ]; then
  echo "Warning: NEXT_PUBLIC_API_HOST not set. Using placeholder."
  NEXT_PUBLIC_API_HOST="https://api-placeholder.awsapprunner.com"
fi

# Build the Docker image using Dockerfile.frontend-production for x86_64 platform (AWS App Runner)
docker build --platform linux/amd64 \
  --build-arg NEXT_PUBLIC_API_HOST="$NEXT_PUBLIC_API_HOST" \
  -f Dockerfile.frontend-production \
  -t $PROJECT_NAME-$DEPLOYMENT_ID-frontend .

# Tag the image for ECR
docker tag $PROJECT_NAME-$DEPLOYMENT_ID-frontend:latest $ECR_REPO_URL:latest

# Push the image to ECR
docker push $ECR_REPO_URL:latest
