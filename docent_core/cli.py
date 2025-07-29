import os
import subprocess
from pathlib import Path

import typer

from docent._log_util import get_logger

logger = get_logger(__name__)
app = typer.Typer(add_completion=False)


@app.command(help="Run the server")
def server(
    host: str = typer.Option("0.0.0.0", help="Host address to bind to"),
    port: int = typer.Option(8888, help="Port to bind to"),
    workers: int = typer.Option(1, help="Number of worker processes"),
    reload: bool = typer.Option(False, help="Enable auto-reload on code changes"),
    timeout_graceful_shutdown: int | None = typer.Option(
        None, help="Timeout in seconds for graceful shutdown when reloading"
    ),
    start_docent_worker: bool = typer.Option(
        True, help="Start a worker process along with the server"
    ),
):
    # `cd` to the server directory; this is where we run uvicorn from (helps for autoreload)
    file_path = Path(__file__).parent.absolute()
    os.chdir(file_path)

    # Run the server with appropriate arguments
    cmd = ["uvicorn", "docent_core._server.api:asgi_app"]
    if host:
        cmd.extend(["--host", host])
    if port:
        cmd.extend(["--port", str(port)])
    if workers:
        cmd.extend(["--workers", str(workers)])
    if reload:
        cmd.append("--reload")
    if timeout_graceful_shutdown is not None:
        cmd.extend(["--timeout-graceful-shutdown", str(timeout_graceful_shutdown)])

    if start_docent_worker:
        logger.info("Starting Docent worker process along with server")
        with subprocess.Popen(["docent_core", "worker"]):
            subprocess.run(cmd, check=True)
    else:
        subprocess.run(cmd, check=True)


@app.command(help="Run a background job runner worker")
def worker():
    from docent_core._worker import worker as docent_worker

    docent_worker.run()


@app.command(help="Run the website")
def web(
    backend_url: str = typer.Option(
        "http://localhost:8888", help="Backend URL for client-side (browser) requests"
    ),
    internal_backend_url: str | None = typer.Option(
        None,
        help=(
            "Internal backend URL for server-side requests. "
            "Only required if the backend is inaccessible from the frontend deployment at the backend_url. "
            "Ex: the Docker Compose setup."
        ),
    ),
    port: int = typer.Option(3000, help="Port to bind to"),
    build: bool = typer.Option(False, help="Build the web app"),
    install: bool = typer.Option(True, help="Install dependencies"),
):
    # `cd` to the web directory; this is where we run npm from
    file_path = Path(__file__).parent / "_web"
    os.chdir(file_path)

    # Create environment with backend URL
    env = os.environ.copy()
    env["NEXT_PUBLIC_API_HOST"] = backend_url
    env["NEXT_PUBLIC_INTERNAL_API_HOST"] = internal_backend_url or backend_url

    # Install dependencies if requested
    if install:
        subprocess.run(["npm", "install", "--legacy-peer-deps"], check=True)

    # Either build or run in debug mode
    if build:
        subprocess.run(["npm", "run", "build"], env=env, check=True)
        subprocess.run(["npm", "run", "start", "--", "--port", str(port)], env=env, check=True)
    else:
        subprocess.run(["npm", "run", "dev", "--", "--port", str(port)], env=env, check=True)


if __name__ == "__main__":
    app()
