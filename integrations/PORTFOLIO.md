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
| Muse Code | coding (Meta) | `.mcp.json` (workspace) | config-ready |
| Claude Code | coding | `.mcp.json` (workspace) | discovered in `claude mcp list`; pending user approval; print-mode blocked by org policy |
| Codex CLI | coding | `~/.codex/config.toml` `[mcp_servers]` | registered + enabled in `codex mcp list`; needs `codex login` for live use |
| OpenCode | coding (OSS) | `opencode.json` `mcp` | **verified: `opencode mcp list` shows switchboard connected** |
| Antigravity | coding/general | MCP config | candidate |

## Tier 2 — under an hour, config or bridge

| Agent | Type | Config we generate | Status |
|---|---|---|---|
| Cursor | IDE coding | `.cursor/mcp.json` | config generated + placed in demo project; app not installed here |
| Claude Desktop | desktop assistant | `claude_desktop_config.json` | config placed at %APPDATA%\Claude; app not installed here |
| Hermes Agent | personal assistant | `~/.hermes/config.yaml` `mcp_servers:` | installed; config listed as enabled; live test blocked by sandbox temp/ACL on spawned processes |
| OpenClaw | personal assistant | `~/.openclaw/openclaw.json` `mcp.servers` | installed; `openclaw mcp list/show` verifies config; live run needs model setup |
| Cline / Roo Code | VS Code coding | VS Code MCP settings JSON | candidate |
| Windsurf | IDE coding | `~/.codeium/windsurf/mcp_config.json` | candidate |

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


