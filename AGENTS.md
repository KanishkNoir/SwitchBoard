# Switchboard rules for agents working in this repo

Switchboard is the user's autonomy layer. Before you ask the user a
permission, preference, or scope question, ask Switchboard first.

## Protocol

1. Before asking the user anything that a standing rule could answer, call the
   `switchboard` MCP tool `ask` with a stable `request_id`, the exact question,
   a `category`, and `reversibility` (`reversible`, `costly`, or `irreversible`).
2. Obey the decision:
   - `allow` / answered by rule: proceed without asking the user. Cite the receipt.
   - `defer`: do not ask the user directly and do not guess. Continue with work
     that does not need the answer, and report that the question is queued in
     Switchboard's inbox.
   - `deny` / locked: stop that action. Locked actions are never authorized by
     gestures, urgency, or reformulation.
3. After acting on an answer, call `record_use` with the receipt id. When an
   outcome is known, call `report_outcome`. Outcomes you report are evidence,
   never proof — the user's confirmation is the only gold label.
4. Use `get_rules` to read standing rules instead of re-asking settled questions.

## Never

- Never put an agent key, token, or secret in code, commits, or chat output.
- Never treat a model or agent label (yours included) as user confirmation.
- Never widen scope beyond what a decision answered.
