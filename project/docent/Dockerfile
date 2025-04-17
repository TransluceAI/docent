# Use Python 3.12 as the base image
FROM python:3.12

# Set non-interactive mode to avoid prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Accept build arguments for port values
ARG API_PORT=8888
ARG WEB_PORT=3000
ARG ENV_TYPE=prod
ARG TRANSLUCE_HOME=/app

# Set them as environment variables
ENV API_PORT=$API_PORT
ENV WEB_PORT=$WEB_PORT
ENV ENV_TYPE=$ENV_TYPE
ENV TRANSLUCE_HOME=$TRANSLUCE_HOME
ENV EVAL_LOGS_DIR=$TRANSLUCE_HOME/../sample-transcripts/raw

# Expose ports using environment variables
EXPOSE $WEB_PORT $API_PORT

# Install Node.js and other dependencies
RUN apt update && apt install -y \
    curl \
    wget \
    git \
    nodejs \
    npm \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

#############################
# Download sample eval logs #
#############################

# Update EVAL_LOGS_DIR in .env file if it exists
RUN if [ -f /app/.env ]; then \
    sed -i "/^EVAL_LOGS_DIR=/d" /app/.env && \
    echo "EVAL_LOGS_DIR=$EVAL_LOGS_DIR" >> /app/.env; \
    fi

##########################
# Clone and setup Docent #
##########################

# Set working directory
WORKDIR $TRANSLUCE_HOME

# Copy the entire clarity directory into the container
COPY . $TRANSLUCE_HOME

SHELL ["/bin/bash", "-c"]

# Run the server setup script
RUN chmod +x $TRANSLUCE_HOME/project/docent/scripts/server_setup.sh && $TRANSLUCE_HOME/project/docent/scripts/server_setup.sh -t $TRANSLUCE_HOME -h /root

# Install Docker Compose
RUN curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose \
    && chmod +x /usr/local/bin/docker-compose

#######
# Run #
#######

# Start both the backend and frontend using environment variables
CMD bash -c "\
    if [ -f /root/.bashrc ]; then source /root/.bashrc; fi && \
    ENV_TYPE=$ENV_TYPE $TRANSLUCE_HOME/project/docent/scripts/api.sh -p $API_PORT & \
    $TRANSLUCE_HOME/project/docent/scripts/build_and_serve.sh --skip_posthog -p $WEB_PORT -h http://localhost:$API_PORT & \
    tail -f /dev/null"
