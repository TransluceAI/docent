#!/bin/bash
set -e

# Default port values
API_PORT=8888
WEB_PORT=3000

# Parse command line arguments
while getopts "a:w:" opt; do
  case $opt in
    a) API_PORT=$OPTARG ;;
    w) WEB_PORT=$OPTARG ;;
    \?) echo "Invalid option: -$OPTARG" >&2; exit 1 ;;
  esac
done

# Run the docker container with the specified ports and capture the container ID
CONTAINER_ID=$(docker run --privileged -d \
    -p $WEB_PORT:$WEB_PORT \
    -p $API_PORT:$API_PORT \
    -e API_PORT=$API_PORT \
    -e WEB_PORT=$WEB_PORT \
    -v /var/run/docker.sock:/var/run/docker.sock \
    docent-preview)

echo "Container started with API port: $API_PORT and Web port: $WEB_PORT"
echo "Container ID: $CONTAINER_ID"

# Helpful commands
echo -e "\nTo tail logs in the future, you can run:"
echo "docker logs -f $CONTAINER_ID"
echo "To enter the container, you can run:"
echo "docker exec -it $CONTAINER_ID bash"

# Show docker logs
echo -e "\nShowing container logs (press Ctrl+C to exit log view):"
docker logs -f $CONTAINER_ID
