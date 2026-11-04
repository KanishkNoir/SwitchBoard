# Public playground

[Open the public playground](https://cogni-noir--switchboard-playground-web.us-east.modal.run) — no login needed.

The playground is a separate Modal app for people who want to try Switchboard without credentials. It uses the real decision service and built React interface with fictional sample agents and choices. It does not connect a visitor's native assistants.

Visitors can answer in Focus, reuse a saved answer from another sample agent, test a project boundary, preview and apply a correction, inspect recorded draft dependencies and a rule-level hold, and steer a sample venue proposal. A deliberate reset starts that visitor's example over.

## Isolation and lifetime

- A random opaque HttpOnly, SameSite cookie selects one in-memory SQLite service and one web route instance. The cookie is Secure over HTTPS. Rule IDs, receipts, caches and event streams belong to that workspace.
- The deployment mounts no volumes and supplies no secrets. It has no access to the private hub ledger or credentials. Browser requests cannot register external agents, use MCP, invoke provider routes or run arbitrary evaluation cases. The outer router denies routes that are not explicitly allowed.
- All initial example events are labelled synthetic. Preloaded rules represent fictional saved choices; no example outcome is counted as real-user calibration. The workspace is not exported to the private product or used to train a model.
- Model calls are off. This playground demonstrates local matching and application policy, not the separately verified Meta/Baseten branch shown in the video. Sample assistants are scripted; their presence does not establish native assistant enforcement.
- Workspaces expire after 30 idle minutes, when the browser cookie expires, or when the container restarts. They cannot be recovered. Do not enter private information.
- One container keeps cookie routing consistent. Up to 64 workspaces are retained, with at most 60 creations per minute, 180 requests per workspace per minute, ten concurrent requests and two event streams per workspace. Streams reconnect after 25 seconds. Input bodies are limited to 16 KiB, and writes pause beyond roughly 4 MiB of workspace database pages. Capacity errors ask the visitor to retry.
- A reset rotates the cookie and retires the old workspace. Its database closes after any in-flight requests finish. Other visitors retain their state. Cross-origin writes are rejected and mutations require JSON.

The route factory loads the existing web module with a supplied isolated service. Each loaded module owns its mutable caches and subscribers. It does not swap a shared global service between requests. The ordinary private application continues to create its usual service when none is supplied.

## Run and deploy

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
uv run uvicorn switchboard.sandbox:app --host 127.0.0.1 --port 8794
```

Open `http://127.0.0.1:8794/`. Use `modal_sandbox.py` for the public deployment, **not** the private hub's `modal_app.py`:

```powershell
$env:SWITCHBOARD_BUILD_ID = "your-git-commit"
modal deploy modal_sandbox.py
```

Do not add `switchboard-secrets`, a persistent volume, or a private hub URL to that app. The existing private operator deployment keeps its own login and ledger.

## Validation

`tests/test_public_sandbox.py` checks visitor isolation, private service preservation, cross-workspace object access, model/API restrictions, actual correction holds and dependency previews, reset, concurrent reads and writes, cache separation, cookie flags, cross-origin writes, request size, capacity and expiry with an in-flight reader. Browser verification covers desktop and phone layouts, guided actions, Focus answers, reset and sample steering.

On November 5, 2026 (India time), live build `fe651c4` passed anonymous access, two independent visitor sessions, scoped reuse, correction preview and hold, Focus answers, individual reset and blocked external APIs. The served frontend asset hash matched the verified build. The full local backend suite passed 244 tests, with subprocess MCP integration enabled, plus the existing OpenCode gate checks and frontend build. Live browser checks covered 1440×1000 and 390×844 without horizontal overflow. These checks establish the sample workflow, not native assistant compliance or real-user performance.
