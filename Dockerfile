# Use Python 3.12 as the base image
FROM python:3.12

# Set non-interactive mode to avoid prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Accept build arguments for port values
ARG SERVER_PORT=8888
ARG WEB_PORT=3000
ARG POSTGRES_USER=docent
ARG POSTGRES_PASSWORD=docent
ARG POSTGRES_DB=docent

# Set them as environment variables
ENV SERVER_PORT=$SERVER_PORT
ENV WEB_PORT=$WEB_PORT

# Expose ports using environment variables
EXPOSE $WEB_PORT $SERVER_PORT

# Install Node.js and other dependencies
RUN apt update && apt install -y \
    curl \
    wget \
    git \
    nodejs \
    npm \
    postgresql \
    && rm -rf /var/lib/apt/lists/*

# Install Redis
RUN apt update && apt install -y lsb-release gpg && \
    curl -fsSL https://packages.redis.io/gpg | gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg && \
    chmod 644 /usr/share/keyrings/redis-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/redis.list && \
    apt update && \
    apt install -y redis

# Configure PostgreSQL with custom user
RUN service postgresql start && \
    su - postgres -c "psql -c \"CREATE USER $POSTGRES_USER WITH PASSWORD '$POSTGRES_PASSWORD';\"" && \
    su - postgres -c "psql -c \"ALTER USER $POSTGRES_USER WITH SUPERUSER;\"" && \
    service postgresql stop

##########################
# Clone and setup Docent #
##########################

# Set working directory and copy the project
WORKDIR /app
COPY . /app
SHELL ["/bin/bash", "-c"]

# Install dependencies
RUN pip install .

#######
# Run #
#######

# Start both the backend and frontend using environment variables
CMD bash -c "\
    if [ -f /root/.bashrc ]; then source /root/.bashrc; fi && \
    service postgresql start && \
    service redis-server start && \
    docent server --port $SERVER_PORT --env .env --workers 4 & \
    docent web --build --port $WEB_PORT --backend-url http://localhost:$SERVER_PORT & \
    tail -f /dev/null"
