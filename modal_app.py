"""Deploy Switchboard to Modal (serverless, fixed URL, persistent ledger).

Setup once (workspace token required — proxy tokens cannot deploy):
  modal token new
  modal secret create switchboard-secrets META_API_KEY=... BASETEN_API_KEY=... \
      MODAL_PROXY_TOKEN_ID=... MODAL_PROXY_TOKEN_SECRET=... SWITCHBOARD_UI_TOKEN=...

Deploy:
  modal deploy modal_app.py
"""
import os

import modal

app = modal.App("switchboard")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi>=0.115", "uvicorn>=0.30", "httpx>=0.27",
                 "pydantic>=2.7", "meta-sam-parser>=0.0.4")
    .add_local_dir("switchboard", remote_path="/app/switchboard")
    .add_local_dir("frontend/dist", remote_path="/app/frontend/dist")
    .add_local_file("pyproject.toml", remote_path="/app/pyproject.toml")
)

volume = modal.Volume.from_name("switchboard-data", create_if_missing=True)
secrets = [modal.Secret.from_name("switchboard-secrets")]


@app.function(image=image, volumes={"/data": volume}, secrets=secrets,
              cpu=1.0, memory=1024, scaledown_window=300)
@modal.asgi_app()
def web():
    import sys
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    os.chdir("/app")
    os.environ.setdefault("SWITCHBOARD_DB", "/data/switchboard.db")
    # Commit volume writes periodically is handled by Modal on container stop;
    # our SQLite WAL lives on the volume at /data.
    from switchboard.app import app as fastapi_app
    return fastapi_app
