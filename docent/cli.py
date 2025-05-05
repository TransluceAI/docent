"""Developer tooling for the monorepo."""

import os
import subprocess
from pathlib import Path
from typing import cast

import typer
from dotenv import dotenv_values

from docent._log_util import get_logger

logger = get_logger(__name__)
app = typer.Typer(add_completion=False)


def _load_dotenv(fpath: str | Path | None = None):
    if fpath is None:
        # Navigate to project root by default
        fpath = Path(__file__).parent.parent.absolute() / ".env"
    else:
        fpath = Path(fpath)

    if not fpath.exists():
        raise FileNotFoundError(
            f"No .env file found at {fpath}. Make sure you've created one, then specify it through the --env argument."
        )

    # Load the .env file and ensure all values are strings
    env_dict = dotenv_values(fpath)
    for k, v in env_dict.items():
        if v is None:
            logger.warning(f"Skipping {k} because it is not set in the .env file")
            del env_dict[k]
    logger.info(f"Loaded .env file from {fpath}")

    # We checked that all values are not None, so we can safely cast
    return cast(dict[str, str], env_dict)


@app.command(help="Run the server")
def server(
    host: str = typer.Option("0.0.0.0", help="Host address to bind to"),
    port: int = typer.Option(8888, help="Port to bind to"),
    workers: int = typer.Option(1, help="Number of worker processes"),
    reload: bool = typer.Option(False, help="Enable auto-reload on code changes"),
    env: str | None = typer.Option(None, help="Path to the .env file"),
):
    env_vars = _load_dotenv(env)

    # `cd` to the server directory; this is where we run uvicorn from (helps for autoreload)
    file_path = Path(__file__).parent.absolute() / "_server"
    os.chdir(file_path)

    # Run the server with appropriate arguments
    cmd = ["uvicorn", "docent._server.api:asgi_app"]
    if host:
        cmd.extend(["--host", host])
    if port:
        cmd.extend(["--port", str(port)])
    if workers:
        cmd.extend(["--workers", str(workers)])
    if reload:
        cmd.append("--reload")

    # Pass current environment variables to the subprocess
    subprocess.run(cmd, check=True, env=os.environ | env_vars)


@app.command(help="Run the website")
def web(
    backend_url: str = typer.Option("http://localhost:8888", help="Backend URL to query"),
    port: int = typer.Option(3000, help="Port to bind to"),
    build: bool = typer.Option(False, help="Build the web app"),
):
    # `cd` to the web directory; this is where we run npm from
    file_path = Path(__file__).parent.absolute() / "_web"
    os.chdir(file_path)

    # Create environment with the backend URL
    env = os.environ.copy()
    env["NEXT_PUBLIC_API_HOST"] = backend_url

    # Either build or run in debug mode
    subprocess.run(["npm", "install"], check=True)
    if build:
        subprocess.run(["npm", "run", "build"], env=env, check=True)
        subprocess.run(["npm", "run", "start", "--", "--port", str(port)], env=env, check=True)
    else:
        subprocess.run(["npm", "run", "dev", "--", "--port", str(port)], env=env, check=True)


if __name__ == "__main__":
    app()
