# Client connection repairs — 4 November 2026

The shared hub is `https://cogni-noir--switchboard-web.us-east.modal.run`.
The former `kanishksingh-1106` workspace URLs return 404 and must be replaced.
All clients use the same persistent ledger; each harness has its own identity.

## Workstation state

| Client | Installed connection | Verification |
|---|---|---|
| Codex desktop / CLI | Global and project MCP entries; dedicated `codex-hub` credential file | Fresh MCP initialization, authenticated identity, nine tools and four rules; CLI sees enabled server |
| Claude Code / extension | Global and project MCP entries; dedicated `claude-code-hub` | Native `claude mcp list` connected; authenticated calls; native PowerShell hook allows reads/control-plane and denies invalid-auth actions |
| OpenCode | Project MCP entry and gate plugin repaired; existing `opencode-hub` identity | Native MCP list connected; authenticated calls; five synthetic gate scenarios and two broken-config startup scenarios pass |
| Muse Code | Existing user settings merged; existing `muse-code-hub` identity | Actual stdio initialization and authenticated tool calls from those settings; provider/model preserved |
| Claude Desktop | Both Roaming and Microsoft Store settings repaired | Actual stdio initialization and authenticated calls from both saved configurations |
| Hermes | Official native Windows installation; `%LOCALAPPDATA%/hermes/config.yaml`; dedicated `hermes-hub` | Native `hermes mcp test switchboard` discovers nine tools; authenticated MCP identity/rules verified |
| Claude / ChatGPT mobile | Hosted OAuth MCP endpoint; separate prepared mobile identities | Real DCR, PKCE authorization, authenticated MCP, refresh and revocation tested; account/device installation remains pending |

The stdio checks launch from an unrelated temporary working directory. Imports,
credentials and ledger paths do not depend on the client's current directory.
Desktop apps and existing chats must reload their MCP servers or start a new
session to use changed settings. A running Codex chat keeps its old MCP process.

Hermes uses the existing Meta model endpoint on Baseten with `model.key_env`;
its provider key stays in Hermes' private `.env`. The hub remains deployed on
Modal with its existing provider secrets. Connection checks do not establish a
successful inference call by every client's model.

Private keys are in ignored credential files, and previous settings and ledger
snapshots are backed up under ignored `.tmp/private-backups`. No actual keys
belong in source, generated examples that will be committed, or command-line
arguments. Existing desktop client identities were preserved.

## Repeatable setup

Run from the Switchboard checkout, or set `SWITCHBOARD_HOME` to its absolute path:

```powershell
uv run python -m switchboard.onboard --agent codex --api-key-file C:/private/codex.key --remote https://cogni-noir--switchboard-web.us-east.modal.run
uv run python -m switchboard.onboard --agent hermes --api-key-file C:/private/hermes.key --remote https://cogni-noir--switchboard-web.us-east.modal.run
```

Merge the generated entry into the client's existing settings. Supported names
also include `claude-code`, `opencode`, `muse`, and `claude-desktop`. The generator
pins project, ledger and cache paths; file references contain no key contents.
For remote OAuth clients, `--transport http --remote https://your-hub` emits the
requested `/mcp` endpoint rather than a localhost placeholder.

Call `get_connection_status` and check `connected`, `backend` and the expected
agent name. Then call `get_rules`. Tool discovery alone does not prove that the
server can authenticate or reach the hub. Failed rule lookups now raise an
explicit tool error instead of silently returning an empty rule set.

## Mobile account step

Use this URL in the account's custom MCP connector/plugin setup:

`https://cogni-noir--switchboard-web.us-east.modal.run/mcp`

Use a dedicated mobile identity at Switchboard's consent page. Its API key is
checked by Switchboard and is not sent to the MCP client. OAuth access tokens
last one hour; refresh tokens last 30 days and rotate. Disabling the associated
agent invalidates access. Disconnect/revoke also revokes its token family.

Browser automation was blocked by automatic approval review before opening
`claude.ai`: browser access to that origin needs an explicit permission grant.
The question covering `claude.ai` and `chatgpt.com` is queued in Switchboard's
inbox as `ec5e2c5a-1627-431e-91b5-5417c56221cf`. No account or phone connection
has been represented as completed.

See the [Claude mobile setup](CLAUDE_MOBILE.md), [official OpenAI remote MCP
guide](https://developers.openai.com/api/docs/guides/custom-mcp-server), and
[official Hermes native Windows guide](https://hermes-agent.nousresearch.com/docs/user-guide/windows-native).
Account plan, workspace policy and mobile app availability still determine
whether each account offers custom connectors.

## Enforcement and deployment

All MCP clients receive ask-first server instructions, including honoring
defer, receipt use and agent-asserted outcomes. Automatic pre-action gates are
installed for Claude Code and OpenCode **in this project**. MCP access on other
surfaces does not by itself intercept every action or guarantee compliance.

Claude Code's tracked `.claude/settings.example.json` uses exec-form arguments
and `onFailure: "block"`; merge it into local settings. The hook reads private
key files and uses the project's pinned Python. OpenCode's gate also reads
private key files. Both block state-changing calls on failed authentication;
read/control-plane calls bypass review to avoid recursion.

The Modal app composes operator and OAuth/MCP routes with their respective
authentication, starts the MCP lifespan, and exposes a build identifier. A
compatibility shim accepts public-client revocation requests that omit the
optional client secret, while retaining SDK client authentication.

Back up and verify the ledger before `modal deploy --strategy recreate modal_app.py`.
This one-container SQLite deployment must avoid overlapping writers. Persistent
streams can delay rolling replacement; `recreate` trades a brief cold start for
a definite replacement. Keep the single-container limit until the ledger is
moved to a database designed for multiple workers.

Validation: 173 isolated backend tests pass, including real local MCP HTTP,
credential-file handling, connection errors, OAuth routing/revocation and
portable config generation. The frontend production build also passes.
