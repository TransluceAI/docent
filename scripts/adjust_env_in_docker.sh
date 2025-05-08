#!/bin/bash
set -e

# Navigate to the parent directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &> /dev/null && pwd )"
cd $SCRIPT_DIR

# Update database connection settings in .env file for Docker environment
if [ -f .env ]; then
  # Replace PostgreSQL host with Docker service name
  sed -i 's/^DOCENT_PG_HOST=.*/DOCENT_PG_HOST=postgres/' .env

  # Replace Redis host with Docker service name
  sed -i 's/^DOCENT_REDIS_HOST=.*/DOCENT_REDIS_HOST=redis/' .env

  echo "Updated .env file with Docker container hostnames"
else
  echo "Error: .env file not found. Please create a .env file based on .env.template before running this script."
  exit 1
fi
