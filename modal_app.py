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


# Single-container by design: the ledger is one SQLite file on the volume.
# Multiple containers each hold a divergent copy of that file (Modal volumes
# sync on commit/stop, not per-write), which made sessions flicker in and out
# as requests landed on different containers. One container = one ledger.
@app.function(image=image, volumes={"/data": volume}, secrets=secrets,
              cpu=1.0, memory=1024, scaledown_window=300,
              min_containers=1, max_containers=1)
@modal.asgi_app()
def web():
    import sys
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    os.chdir("/app")
    os.environ.setdefault("SWITCHBOARD_DB", "/data/switchboard.db")
    # Rollback-journal mode on the hub: WAL is unsupported over a network
    # filesystem (sqlite.org/wal.html) and the volume is commit/reload object
    # storage, not a live shared FS. Local dev keeps WAL for speed.
    os.environ.setdefault("SWITCHBOARD_JOURNAL_MODE", "delete")
    from switchboard.app import app as fastapi_app
    return fastapi_app

