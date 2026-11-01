# Claude Code automatic action gate

The project-local Claude Code hook routes tool calls through Switchboard before
execution. It applies to Claude Code sessions opened in this workspace after
the hooks load.

## Enable it

1. Make sure the Switchboard hub is reachable and the existing workspace
   `switchboard` MCP server can authenticate. The hook reads its agent key from
   the process environment or the existing `.mcp.json` in memory; it does not
   print or copy the key.
2. Restart Claude Code with this workspace open so it loads
   `.claude/settings.local.json`.
3. Try a tool call that can change state. If Switchboard defers the request,
   that call stays blocked while the hook waits for an answer in the Switchboard
   inbox, for up to five minutes by default. An explicit one-time allow lets the
   call proceed; deny, timeout, missing credentials, or hub failure blocks it.

Read-only tools (`Read`, `Glob`, `Grep`, `WebFetch`, `WebSearch`,
`NotebookRead`, and `LS`) pass without review. Switchboard MCP tools bypass the
gate to prevent recursion. `AskUserQuestion` is sent to Switchboard as a
preference question; a selected answer is returned to Claude Code in place of
showing the normal question prompt. Multi-select questions are blocked because
the adapter currently maps one choice per question.

Only the tool name, argument field names, target file basename, and the first
two shell-command words are sent as action context. Tool argument bodies are
not sent. Outcomes are reported as agent-provided evidence, not user-confirmed
labels.

This hook controls tool calls made by Claude Code in this workspace. It does
not control Claude mobile or other apps that only connect to the remote MCP
server; those clients need their own supported pre-action hook to enforce the
same gate.
