import modal
from pathlib import Path

def find_project_root() -> Path:
    current_dir = Path(__file__).resolve().parent
    while current_dir != current_dir.parent:
        if (current_dir / ".env").exists():
            return current_dir
        current_dir = current_dir.parent
    raise RuntimeError("Could not find project root; no .env file found in parent directories")

REMOTE_ROOT = Path("/root/docent")
LOCAL_ROOT = find_project_root()

print(f"Local root: {LOCAL_ROOT}")
print(f"Remote root: {REMOTE_ROOT}")

app = modal.App("docent-server")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("uv")
    .add_local_file(f"{LOCAL_ROOT}/pyproject.toml", f"{REMOTE_ROOT}/pyproject.toml", copy=True)
    .run_commands(f"cd {REMOTE_ROOT} && uv pip install --system -e .")
    .add_local_file(f"{LOCAL_ROOT}/.env", f"/root/.env", copy=True)
    .add_local_python_source("docent", copy=True)
)

@app.function(
    image=image,
    region="us-east-1",
)
@modal.asgi_app(custom_domains=["docent-backend.transluce.org"])
def fastapi_app():
    from docent._server.api import asgi_app
    return asgi_app 