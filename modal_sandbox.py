"""Public sample workspace. Separate app; deliberately NO secrets or volumes.

Build frontend/dist, then: modal deploy modal_sandbox.py
"""
import os
import modal

app = modal.App("switchboard-playground")
image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("fastapi>=0.115", "uvicorn>=0.30", "httpx>=0.27", "pydantic>=2.7")
         .add_local_dir("switchboard", remote_path="/app/switchboard")
         .add_local_dir("frontend/dist", remote_path="/app/frontend/dist"))


@app.function(image=image, cpu=1.0, memory=1024, min_containers=1, max_containers=1,
              env={"SWITCHBOARD_DB": ":memory:", "SWITCHBOARD_ENABLE_T3": "false",
                   "SWITCHBOARD_BUILD_ID": os.environ.get("SWITCHBOARD_BUILD_ID", "development")})
@modal.concurrent(max_inputs=128, target_inputs=32)
@modal.asgi_app()
def web():
    import sys
    sys.path.insert(0, "/app")
    os.chdir("/app")
    from switchboard.sandbox import app as sandbox_app
    return sandbox_app
