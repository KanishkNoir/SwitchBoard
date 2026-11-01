# Claude mobile connector

Switchboard's Modal deployment can expose an authenticated Streamable HTTP MCP
endpoint for Claude. Configure the connector once from Claude web; Claude's iOS
and Android apps can then use connectors already added to the account.

## Enable the hosted MCP endpoint

1. Set `SWITCHBOARD_MCP_PUBLIC_URL` in the local deployment shell to the HTTPS
   origin of the deployed `web` function. Use the origin only; do not add
   `/mcp` or a trailing slash. Modal API credentials remain in the existing
   Modal profile or `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` environment vars.
2. Deploy with `modal deploy modal_app.py`; the app forwards this public URL to
   the worker as a runtime environment value. It is configuration, not a secret.
3. Confirm the deployment exposes `/mcp` and its OAuth discovery endpoints.

The MCP endpoint shares the web worker's Switchboard service and SQLite store.
Keep the current one-container limit while the hub uses the SQLite Volume.

## Connect Claude

1. Register a dedicated agent named `claude-mobile` in Switchboard's Agents &
   rules page and securely copy its one-time `sb_…` key.
2. In Claude web, open **Settings → Connectors → Add custom connector** and set
   the URL to `<SWITCHBOARD_MCP_PUBLIC_URL>/mcp`.
3. When Claude opens Switchboard's consent page, enter the dedicated agent key.
   Switchboard validates it against the backend, then issues OAuth tokens tied
   to that agent. The key is not given to Claude.
4. Add an ask-first instruction in Claude's custom instructions: use
   `switchboard.ask` before making a preference or authorization decision;
   honor its scope and decision, and defer to the user when Switchboard defers.
5. Test the connection with `switchboard.get_rules` (read-only), then enable the
   connector in Claude mobile.

To revoke access, disconnect the connector in Claude or disable the associated
`claude-mobile` agent in Switchboard.

Claude remote connectors are documented for paid plans, and servers must be
added through Claude web before they can be used on mobile. See [Anthropic's
remote MCP guide](https://support.anthropic.com/en/articles/11503834-building-custom-integrations-via-remote-mcp-servers).
