import os
import subprocess
from pathlib import Path

import typer

app = typer.Typer(add_completion=False)


@app.command(help="Run the server")
def server(
    host: str = typer.Option("0.0.0.0", help="Host address to bind to"),
    port: int = typer.Option(8888, help="Port to bind to"),
    workers: int = typer.Option(1, help="Number of worker processes"),
    reload: bool = typer.Option(False, help="Enable auto-reload on code changes"),
):
    # `cd` to the server directory; this is where we run uvicorn from (helps for autoreload)
    file_path = Path(__file__).parent.parent.parent.absolute() / "docent"
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

    subprocess.run(cmd, check=True)


@app.command(help="Run the website")
def web(
    backend_url: str = typer.Option("http://localhost:8888", help="Backend URL to query"),
    port: int = typer.Option(3000, help="Port to bind to"),
    build: bool = typer.Option(False, help="Build the web app"),
    install: bool = typer.Option(True, help="Install dependencies"),
):
    # `cd` to the web directory; this is where we run npm from
    file_path = Path(__file__).parent.parent.parent.absolute() / "docent" / "_web"
    os.chdir(file_path)

    # Create environment with the backend URL
    env = os.environ.copy()
    env["NEXT_PUBLIC_API_HOST"] = backend_url

    # Install dependencies if requested
    if install:
        subprocess.run(["npm", "install"], check=True)

    # Either build or run in debug mode
    if build:
        subprocess.run(["npm", "run", "build"], env=env, check=True)
        subprocess.run(["npm", "run", "start", "--", "--port", str(port)], env=env, check=True)
    else:
        # Use Popen instead of run for the dev server to enable hot reloading
        process = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(port)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        try:
            # Stream the output
            while True:
                output = process.stdout.readline() if process.stdout else None
                if output == "" and process.poll() is not None:
                    break
                if output:
                    print(output.strip())

            # Check for any errors
            if process.returncode != 0:
                error = process.stderr.read() if process.stderr else None
                raise subprocess.CalledProcessError(process.returncode, process.args, error)
        except KeyboardInterrupt:
            process.terminate()
            process.wait()


if __name__ == "__main__":
    app()
