"""Deploy Switchboard to Modal (serverless, fixed URL, persistent ledger).

Setup once (workspace token required — proxy tokens cannot deploy):
  modal token new
  # Set SWITCHBOARD_MCP_PUBLIC_URL in the deployment shell to enable remote MCP.
  modal secret create switchboard-secrets META_API_KEY=... BASETEN_API_KEY=... \
      MODAL_PROXY_TOKEN_ID=... MODAL_PROXY_TOKEN_SECRET=... SWITCHBOARD_UI_TOKEN=...

Deploy:
  modal deploy --strategy recreate modal_app.py

Use recreate for this single-writer SQLite deployment: overlapping rolling
workers can overwrite each other's volume snapshot, and persistent streams
can delay a rolling replacement. Back up the volume before deploying.
"""
import os

import modal

app = modal.App("switchboard")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi>=0.115", "uvicorn>=0.30", "httpx>=0.27",
                 "pydantic>=2.7", "mcp>=2.3,<3", "meta-sam-parser>=0.0.4")
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
              env={key: value for key in ("SWITCHBOARD_MCP_PUBLIC_URL", "SWITCHBOARD_BUILD_ID")
                   if (value := os.environ.get(key))},
              cpu=1.0, memory=1024, scaledown_window=300,
              min_containers=1, max_containers=1)
@modal.concurrent(max_inputs=64, target_inputs=16)
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
    public_mcp_url = os.environ.get("SWITCHBOARD_MCP_PUBLIC_URL", "").rstrip("/")
    if not public_mcp_url:
        return fastapi_app

    from switchboard.app import svc as web_service
    from switchboard import mcp_server
    mcp_server.bind_service(web_service)
    mcp_server.use_local_backend()
    mcp_app = mcp_server.hosted_http_app()

    # Mounted apps do not receive Starlette lifespan events automatically.
    from switchboard.hosting import combined_app
    return combined_app(fastapi_app, mcp_app, mcp_server.mcp.session_manager)

