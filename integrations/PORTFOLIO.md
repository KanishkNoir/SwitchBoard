# Switchboard integration portfolio

Switchboard is agent-agnostic: any MCP-capable agent can call `ask`, `get_rules`,
`report_outcome`, and `record_use`. This portfolio ranks real-world agents by
**integration speed** — time from "user has the agent" to "agent asks Switchboard
before asking the user" — and tracks honest verification status.

Verification levels:

- **protocol-verified** — a real MCP client completed ask/record_use/report_outcome
  against our server (stdio and/or Streamable HTTP).
- **config-ready** — we ship a generated config for the agent's documented MCP
  format; not yet run inside that vendor's product in this workspace.
- **candidate** — surface identified, config not yet generated.

## Tier 1 — minutes, MCP-native, high question volume

| Agent | Type | Config we generate | Status |
|---|---|---|---|
| Muse Code | coding (Meta) | `mcpServers` block in `~/.config/muse/settings.json` | **verified live on the hub (1.4.14): headless run called `ask` via `--remote` config, question recorded in the Modal inbox as `muse-code-hub`** |
| Claude Code | coding | `.mcp.json` (workspace) | discovered in `claude mcp list`; pending user approval; print-mode blocked by org policy |
| Codex CLI | coding | `~/.codex/config.toml` `[mcp_servers]` | registered + enabled in `codex mcp list`; needs `codex login` for live use |
| OpenCode | coding (OSS) | `opencode.json` `mcp` | **verified live: free model `opencode/big-pickle` called `ask`, decision recorded in ledger; `opencode mcp list` shows switchboard connected** |
| Antigravity | coding/general | MCP config | candidate |

## Tier 2 — under an hour, config or bridge

| Agent | Type | Config we generate | Status |
|---|---|---|---|
| Cursor | IDE coding | `.cursor/mcp.json` | config generated + placed in demo project; app not installed here |
| Claude Desktop | desktop assistant | `claude_desktop_config.json` | **protocol-verified with the installed config at %APPDATA%\Claude (dedicated `claude-desktop` agent, pinned ledger paths); restart the app to pick it up** |
| ChatGPT desktop/web | desktop assistant | remote MCP app (Developer Mode) | **retired 2026-10-30: endpoint removed (no paid plan; unused attack surface). Rebuild = re-add the `mcp_api` ASGI function to modal_app.py; local MCP clients never used it** |
| Hermes Agent | personal assistant | `~/.hermes/config.yaml` `mcp_servers:` | **verified live on the hub: runs on Baseten `meta-models/muse-spark-open-1026` (openai-api provider + OPENAI_BASE_URL), called `ask`, question recorded in the Modal inbox as `hermes-hub`; startup needs edge-tts preinstalled in its venv and direct venv-python spawn (uv cache ACL)** |
| OpenClaw | personal assistant | `~/.openclaw/openclaw.json` `mcp.servers` | installed; `openclaw mcp list/show` verifies config; live run needs model setup |
| Cline / Roo Code | VS Code coding | VS Code MCP settings JSON | candidate |
| Windsurf | IDE coding | `~/.codeium/windsurf/mcp_config.json` | candidate |

> Parked by decision: harness expansion stops here. The pattern is proven —
> any MCP-capable agent works by generating its config with `switchboard.onboard`
> (local stdio, or `--remote` for the device-agnostic hub), registering one
> agent key, and adding the ask-first rule to its instructions. Remaining
> candidates need no new engineering, only per-app config placement.

## Tier 3 — advisory only (closed harnesses)

Devin, cloud Copilot agents, consumer ChatGPT/Claude apps: no supported way to
route their questions through Switchboard or enforce its decisions. We can offer
them preference context, but Switchboard cannot be their authorization layer.
Listed for honesty, not targeted.

## Why this order

1. **Question volume:** coding agents ask permission/preference questions all day.
2. **Shared human:** one user runs 2–3 of these; one answer in Switchboard serves all.
3. **Personal assistants are the product proof:** OpenClaw/Hermes ask about travel,
   messages, and purchases — the categories where scope and blast radius matter most
   to non-developers. Tier 2 by config effort, Tier 1 by strategic value.

## Generate a config

```powershell
uv run python -m switchboard.onboard --agent codex --api-key sb_... --out integrations/generated
uv run python -m switchboard.onboard --list
```

Every generated config uses the registered agent key (identity from credentials,
never payload JSON) and points at the local Switchboard MCP server (stdio by
default, or `--transport http` for `http://127.0.0.1:8766/mcp` where supported).

## Device-agnostic hub mode

With `--remote https://kanishksingh-1106--switchboard-web.us-east.modal.run`,
the generated stdio config also sets `SWITCHBOARD_REMOTE_URL`: the MCP server
then proxies every call to the Modal hub, so agents on any machine share one
ledger and the owner answers once from any device (phone web UI included).
The hub is the single source of truth in this mode. Hub agent registration is
gated by the UI token (`POST /api/agents/register` returns 401 without it);
an unreachable hub fails closed to `defer`. OpenCode in this repo already runs
in hub mode (verified: question recorded on Modal, absent locally).


