# Switchboard connection audit — 3 November 2026

The integrations are not all connected correctly. This audit checked installed
clients, saved launch settings, existing credentials, actual MCP requests,
deployment metadata, and the two harness gates. No agent model calls were made.

## Deployment and shared root cause

Modal reports the existing `switchboard` app as deployed, version 5, last deployed
1 November 2026. Its function's canonical URL is:

https://cogni-noir--switchboard-web.us-east.modal.run

That URL returns HTTP 200 for `/health`. Existing OpenCode, Muse Code, and both
Claude Desktop configuration keys return HTTP 200 for `/api/rules` there.
With only the URL substituted in memory, all four configurations complete a
real stdio initialize / tools-list / get-rules sequence successfully.

The saved configurations still use the old workspace address:

https://kanishksingh-1106--switchboard-web.us-east.modal.run

That address returns HTTP 404, including `/health` and `/api/rules`. The standard
non-regional variant of the old address also returns 404.

No local web backend was listening on `127.0.0.1:8765` during this audit.

The live deployment also predates the backend fixes in commit `a4ba6ad` and
advertises an older capability set. A local passing test suite is not evidence
that the deployed instance contains the same implementation.

## Installed clients

| Client | Observed state | Connection result | Action enforcement |
|---|---|---|---|
| Codex desktop / CLI | CLI 0.166.0-alpha.5.1; logged in through ChatGPT; project server enabled | Broken: project `.codex/config.toml` supplies no agent key. `get_rules` in the current chat returns an error. | Ask-first project instructions exist; no Switchboard pre-tool gate was found for Codex. |
| Claude Code / VS Code extension | CLI 2.1.312; authenticated; extensions installed | Broken: project `.mcp.json` uses an unresolved `${SWITCHBOARD_AGENT_KEY}` placeholder. Native `claude mcp list` warns that the variable is missing. | Hook installed; native PowerShell tests allow `Read` and deny a state-changing request with invalid credentials. Startup/failure handling still needs hardening. |
| OpenCode | 1.19.5 installed under the project's tools directory | Native CLI says connected, but the configured hub URL returns 404. Existing key and actual tool calls work with the canonical URL substituted. | Project plugin exists. Five synthetic tests passed for read/control-plane bypass, invalid authentication, failed receipt recording, and allow/use/outcome ordering. No real tool action was executed. |
| Muse Code | 1.4.14 installed | Saved URL is stale. Existing key and actual MCP calls work with the canonical URL substituted. | MCP and project instructions are available; no automatic Switchboard pre-tool gate was verified. |
| Claude Desktop | Roaming and Windows Store configuration files both exist | Both use the stale URL. Both keys and actual MCP calls work with the canonical URL substituted. | MCP provides tools; no application-level action interception was demonstrated. |
| OpenClaw | 2026.5.7 installed under the project's tools directory | Native `mcp list --json` returns `{}`. No active `~/.openclaw/openclaw.json` exists. A generated snippet is not an installed connection. | No active Switchboard pre-tool gate was found. |
| Hermes Agent | Generated YAML exists | No executable on PATH, no `~/.hermes/config.yaml`, and no WSL distribution was found. A prior claim of a live run does not establish a current installation here. | Not verified. |
| Cursor | Generated snippet and demo-project config exist; installer downloaded | No installed runtime was found in the checked paths. Generic MCP works from the repo, but its saved relative ledger path fails the arbitrary-working-directory probe. | Not verified in Cursor. |

The generated Cursor, Hermes, and OpenClaw snippets share the local
`tier2-harnesses` identity. That is suitable for a labelled protocol demo, but it
does not establish separate installed clients or per-harness attribution.

## Other listed harnesses and surfaces

| Surface | Current evidence |
|---|---|
| VS Code MCP / Copilot | The user's `Code/User/mcp.json` is empty. No separate Switchboard registration there was established. The installed Claude extension inherits the Claude Code issue above. |
| Windsurf | No executable or expected user MCP config was found. Candidate support, not a verified installation. |
| Antigravity | No executable or expected MCP config was found. Candidate support, not a verified installation. |
| Cline / Roo Code | Neither extension was found in the inspected stable or Insiders extension directories. Candidate support only. |
| Claude mobile / web connector | Not verified in the user's account/device. The current deployment cannot provide the required hosted MCP/OAuth routes. |
| ChatGPT web / mobile | Not verified in the user's account/device. The same hosted MCP blocker applies. The portfolio's blanket claim that mobile is unsupported is stale; current OpenAI documentation supports plugins on mobile subject to account availability and plugin type. |
| Consumer Muse | Not demonstrated and not a dependency of this project. Do not confuse it with the installed Muse Code CLI. |
| Devin / cloud Copilot agents | No installed or configured integration was established by this audit. No universal enforcement claim is warranted. |

## Hosted MCP is not currently available

On the canonical hub, unauthenticated requests to `/mcp` and OAuth discovery
paths return the human UI gate's 401. Supplying the existing operator UI token
reveals HTTP 404 for:

- `/mcp`
- `/.well-known/oauth-authorization-server`
- `/.well-known/oauth-protected-resource/mcp`

These are absent routes, not a working OAuth challenge. The source already has
a combined hosted MCP deployment path, but the observed deployment is older.
Configure `SWITCHBOARD_MCP_PUBLIC_URL` to the canonical origin when preparing
the next deployment, then test discovery and a genuine authorized MCP request.

## Handshake success can conceal a broken connection

`HubClient.get_rules()` returns an empty list after any HTTP/transport failure.
Consequently, MCP can initialize, list eight tools, and return an apparently
successful empty rule list while the configured backend is returning 404.
OpenCode's native connected indicator reproduces this distinction.

A connection should be called verified only after both an authenticated backend
request and an actual tool call succeed against the configured target. Reading
an empty list alone cannot distinguish no rules from a failed backend.

## Gate limits

The Claude PowerShell wrapper was executed with synthetic hook input. It
returned an allow for `Read` and a deny for a `Write` request with deliberately
invalid credentials. The write tool itself was never executed.

Its `PreToolUse` configuration does not declare `onFailure: "block"`. On the
installed supported Claude version, official guidance requires that setting to
ensure a hook crash, missing executable, or timeout blocks the action. A Python
handler returning a deny does not prove that failure to launch the handler is
also enforced.

OpenCode's five tests use synthetic API responses, not human confirmation or
live correctness evidence. They validate the plugin's control flow, not that
every installed OpenCode action is intercepted. Both gates currently send a
minimized action summary, not a complete action hash verified at execution.

## Model configuration observed

- Muse Code selects the Meta provider and `muse-spark-1.3`.
- OpenCode selects `opencode/big-pickle`.
- The backend `.env` selects Modal reasoning and enables T3.
- Baseten access and the Meta model adapter remain present in the backend.

This audit did not change providers, check model quota, or make paid model calls.

## Repair order

1. Update the existing valid client configurations to the canonical Modal URL.
2. Give Codex and Claude Code dedicated registered credentials through private
   configuration or environment, and pin project/database paths.
3. Add explicit failure blocking to the Claude pre-tool hook and verify it in a
   fresh native session.
4. Deploy the tested current backend with its canonical hosted MCP public URL;
   verify OAuth discovery, token issuance, and an authenticated MCP call.
5. Stop treating a failed remote rule lookup as a successful empty rule list in
   diagnostic flows.
6. Install/merge configurations and verify the actual runtime for OpenClaw,
   Hermes, and Cursor before labelling those integrations connected. Use
   distinct identities rather than the shared demonstration key.
7. Verify actual browser/mobile account connections after hosted MCP works.

The saved client configurations were left unchanged during this audit. The
successful canonical-URL tests used in-memory substitutions only. No app was
restarted, no deployment was changed, and no human approval was fabricated.

## Evidence and documentation

Local machine-readable results: `.tmp/integration-audit.json` (credentials
excluded). Probe scripts: `.tmp/audit_clients.py` and `.tmp/audit_gates.mjs`.

- [Codex MCP configuration](https://developers.openai.com/codex/mcp/)
- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [Claude hook failure behavior](https://code.claude.com/docs/en/hooks#block-the-action-when-a-hook-fails)
- [OpenCode MCP](https://opencode.ai/docs/mcp-servers/)
- [OpenClaw MCP](https://docs.openclaw.ai/tools/mcp)
- [Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)
- [Modal web function URLs](https://modal.com/docs/guide/webhook-urls)
- [ChatGPT plugin surfaces](https://learn.chatgpt.com/docs/plugins)
