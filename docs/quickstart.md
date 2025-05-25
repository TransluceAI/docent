# Quickstart (self-host)

We don't offer a hosted version of Docent yet, but plan to soon. Luckily, self-hosting is easy and free. For larger organizations, we provide white-glove hosting services; please [reach out](mailto:kevin@transluce.org) if you're interested.

### 1. Clone the repo and configure `.env`

```bash
git clone https://github.com/TransluceAI/docent.git
cd docent
cp .env.template .env
```

You should now have a `.env` file at the project root. See [here for details on how to fill it in](./concepts/configuration/environment_variables.md).

### 2. Start the backend server and frontend UI

Docker Compose is the easiest way to get started, but you may want a manual installation to support faster development loops (e.g., for hot reloading).

=== "Docker Compose (recommended)"

    First ensure [Docker Engine](https://docs.docker.com/engine/install/) and [Docker Compose](https://docs.docker.com/compose/install/) are installed. Then run:

    === "As non-root"
        ```bash
        DOCENT_SERVER_PORT=8889 DOCENT_WEB_PORT=3001 docker compose up --build
        ```

    === "As root"
        ```bash
        # Note that `sudo` strips environment variables, so you have to set them *inside* the command.
        sudo DOCENT_SERVER_PORT=8889 DOCENT_WEB_PORT=3001 docker compose up --build
        ```

    Cold build + start should take a few minutes. Once finished, you can run

    === "As non-root"
        ```bash
        docker ps
        ```

    === "As root"
        ```bash
        sudo docker ps
        ```

    to check that the four following containers are running:
    ```bash
    CONTAINER ID   IMAGE             COMMAND                  CREATED          STATUS          PORTS                                         NAMES
    b8bba5b86251   docent-backend    "bash -c 'bash /app/…"   34 seconds ago   Up 33 seconds   0.0.0.0:8889->8889/tcp, [::]:8889->8889/tcp   docent_backend
    0cfc73d80407   docent-frontend   "docent web --build …"   34 seconds ago   Up 33 seconds   0.0.0.0:3001->3001/tcp, [::]:3001->3001/tcp   docent_frontend
    c80f4302db12   postgres:15       "docker-entrypoint.s…"   34 seconds ago   Up 33 seconds   0.0.0.0:5432->5432/tcp, [::]:5432->5432/tcp   docent_postgres
    f9d86be37643   redis:alpine      "docker-entrypoint.s…"   34 seconds ago   Up 33 seconds   0.0.0.0:6379->6379/tcp, [::]:6379->6379/tcp   docent_redis
    ```

    To shut Docent down, either press `Ctrl+C` in the terminal or run:

    === "As non-root"
        ```bash
        docker compose down
        ```

    === "As root"
        ```bash
        sudo docker compose down
        ```

    !!! note
        If you make changes to the codebase, you'll need to stop the containers, then rebuild by **keeping the `--build` argument**. If `--build` is omitted, your changes will not be reflected.

=== "Manual"

    If you don't already have Postgres and Redis installed, you can start them with Docker:

    === "As non-root"
        ```bash
        docker compose -f docker-compose-db.yml up --build
        ```

    === "As root"
        ```bash
        sudo docker compose -f docker-compose-db.yml up --build
        ```

    after which Postgres and Redis will be available at the addresses set in [`.env`](./concepts/configuration/environment_variables.md). To set up your own databases, visit the official docs for [Postgres](https://www.postgresql.org/download/) and [Redis](https://redis.io/docs/latest/operate/oss_and_stack/install/archive/install-redis/).

    Once your databases are up, run:

    === "uv"
        ```bash
        uv sync
        ```

    === "pip"
        ```bash
        pip install -e .
        ```

    to install the relevant server packages, then

    === "Prod"
        ```bash
        docent server --port 8889 --workers 4
        ```

    === "Dev (with autoreload)"
        ```bash
        docent server --port 8889 --reload
        ```

    to run the server, then

    === "Prod"
        ```bash
        docent web --port 3001 --backend-url http://localhost:8889
        ```

    === "Dev (with autoreload)"
        ```bash
        docent web --build --port 3001 --backend-url http://localhost:8889
        ```

    to run the frontend. You may need to [install Node.js](https://nodejs.org/en/download/) first.

Finally, check that you can access the Docent UI at [`http://localhost:3001`](http://localhost:3001).

### 3. Install the Python SDK

In order to load transcripts into Docent, you'll need to install the Docent Python SDK locally.

=== "Docker Compose (recommended)"

    Install the repo into your local Python environment:

    === "uv"
        ```bash
        # Create a new venv for Docent
        uv sync

        # Or install into an existing uv venv
        uv pip install -e .
        ```

    === "pip"
        ```bash
        pip install -e .
        ```

=== "Manual"

    Since you installed the repo locally as part of the manual installation in [Step 2](#2-start-the-backend-server-and-frontend-ui), you can skip this step. If this isn't the case, click the "Docker Compose" tab above.

To verify the installation, run this command, after which you should see no output:

```bash
python -c "import docent"
```


You're all set! Check out some of our [tutorials](./tutorials/ingesting_agent_runs.md) to get started.
