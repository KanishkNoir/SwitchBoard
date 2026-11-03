# OpenCode automatic action gate

Switchboard's project plugin uses OpenCode's `tool.execute.before` hook. It
checks non-read-only tool calls before execution, queues the exact request for
the human when policy defers, and keeps the action blocked until the user
answers **Allow this action once** in Switchboard. It records receipt use before
the tool runs and reports the completed tool call afterward.

## Enable it

1. Ensure `SWITCHBOARD_AGENT_KEY` (or `SWITCHBOARD_AGENT_KEY_FILE`) and `SWITCHBOARD_REMOTE_URL` are available to
OpenCode's process. For this workspace the plugin can also read the Switchboard
server values from `opencode.json`; it never prints the key.
2. Restart OpenCode so it loads `.opencode/plugins/switchboard-gate.js`.
3. Try a file edit or another tool call that can change state. The gate should
show a pending Switchboard request and hold the action until you answer.

Built-in read tools (`read`, `glob`, `grep`, `list`, `webfetch`, `websearch`,
and LSP inspection) pass without a gate. Switchboard's own tools bypass the
gate to prevent recursion. Other tool calls, including shell commands and
third-party MCP tools, are gated conservatively. Unknown actions remain queued
until a human answer is available. A missing key, unreachable hub, failed
audit write, or timeout blocks the action.

Only the tool name, argument field names, a file basename, and the first two
shell-command words are sent as action context; argument bodies are not sent.
Switchboard requires an explicit `allow` answer. Other answers block the call.

This adapter controls tools called through OpenCode. It does not intercept
actions performed outside OpenCode, and other harnesses need their own
pre-action adapter. Claude mobile still depends on its connector instructions.
