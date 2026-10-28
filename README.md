# Switchboard

Local-first personal autonomy layer for compatible AI agents. "Your agents learn when to ask."

MCP `ask` with versioned scoped rules, hard locks,
Shadow/Suggest/Auto stages, receipts, preference supersession with blast radius, attention queue,
evidence integrity, Autonomy Passport, sandbox action binding, replay evaluation, and two demo
agents (Visual Scout, Trade-off Planner) with a four-edge directional UI.

## Run

```powershell
uv sync
uv run python -m switchboard.app   # http://127.0.0.1:8765
```

Open http://127.0.0.1:8765 in a browser (serves the built React UI from `frontend/dist`).

## Frontend development

The UI is a React + TypeScript app in `frontend/` (the old single-file page remains as a fallback).

```powershell
cd frontend
npm install
npm run dev      # http://127.0.0.1:5173 — proxies API calls to the backend on :8765
npm run build    # emits frontend/dist, which FastAPI then serves at /
```

## MCP server (stdio)

Register an agent first via `POST /api/agents/register`, then set its key:

```powershell
$env:SWITCHBOARD_AGENT_KEY = "sb_..."
uv run python -m switchboard.mcp_server
```

Tools: `ask`, `get_rules`, `report_outcome`, `record_use`.

Streamable HTTP transport (agent identity is server-side via `SWITCHBOARD_AGENT_KEY`):

```powershell
$env:SWITCHBOARD_MCP_TRANSPORT = "streamable-http"   # http://127.0.0.1:8766/mcp
uv run python -m switchboard.mcp_server
```

A demo external harness (a separate process speaking only MCP) lives in
[harness/external_harness.py](/C:/Users/Admin/OneDrive/Desktop/Switchboard/harness/external_harness.py);
a workspace `.mcp.json` registration is included for MCP-compatible clients.

## Optional model adapters (off by default)

Copy `.env.example` to `.env`. Set `SWITCHBOARD_ENABLE_T3=true` and pick
`SWITCHBOARD_REASONING_PROVIDER` (`modal`, `baseten`, or `meta`); the ladder tries your pick first
and falls back through the others. Verified integrations: Modal-hosted Muse Spark Open
(`MODAL_CHAT_URL` + proxy token pair), Baseten `meta-models/muse-spark-open-1026` (the hackathon
model for the provided key), and Meta Model API `muse-spark-1.3` via `META_API_KEY`
(`sam-3.1` / `muse-image-1.0` also available on that key). Any provider failure defers; it never
guesses an answer.

## Test

```powershell
uv run pytest -q
```

## Notes

- Agent self-reports are stored as `agent_asserted` evidence and never enter the gold calibration set.
- A configured risk target is a policy goal, not a guaranteed error rate.
- Locked classes (money, deletion, new recipients, irreversible actions) always defer in v1.
