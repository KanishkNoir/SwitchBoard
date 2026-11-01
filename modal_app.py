"""Deploy Switchboard to Modal (serverless, fixed URL, persistent ledger).

Setup once (workspace token required — proxy tokens cannot deploy):
  modal token new
  # Set SWITCHBOARD_MCP_PUBLIC_URL in the deployment shell to enable remote MCP.
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
              env={"SWITCHBOARD_MCP_PUBLIC_URL": os.environ.get("SWITCHBOARD_MCP_PUBLIC_URL")},
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
    from contextlib import asynccontextmanager
    mcp_server.bind_service(web_service)
    mcp_server.use_local_backend()
    mcp_app = mcp_server.hosted_http_app()

    # The MCP app is dispatched as a sub-application below. Starlette does not
    # run mounted apps' lifespans, so enter its session manager from the host
    # FastAPI lifespan or POST /mcp fails with "Task group is not initialized".
    web_lifespan = fastapi_app.router.lifespan_context

    @asynccontextmanager
    async def combined_lifespan(application):
        async with web_lifespan(application):
            async with mcp_server.mcp.session_manager.run():
                yield

    fastapi_app.router.lifespan_context = combined_lifespan

    class CombinedASGI:
        """Serve web/API and MCP in one worker so SQLite has one shared owner."""

        def __init__(self, web_app, remote_mcp_app):
            self.web_app = web_app
            self.remote_mcp_app = remote_mcp_app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                path = scope.get("path", "")
                is_mcp = (
                    path == "/mcp"
                    or path.startswith("/.well-known/")
                    or path in {"/authorize", "/token", "/register", "/revoke", "/oauth/consent"}
                )
                if is_mcp:
                    return await self.remote_mcp_app(scope, receive, send)
            return await self.web_app(scope, receive, send)

    return CombinedASGI(fastapi_app, mcp_app)

