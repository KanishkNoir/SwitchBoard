# Mobile agents and Focus mode

Claude and ChatGPT use the hosted OAuth MCP connector to reach the shared
Switchboard ledger. You review their questions in Switchboard's mobile web
interface, where **Focus mode** presents one decision at a time.

## Current verification — 4 November 2026

- Claude's account connector has an active OAuth grant for `claude-mobile-mcp`.
  A live Claude chat called `get_connection_status` and `get_rules` successfully.
- ChatGPT's installed Switchboard plugin has an active OAuth grant for
  `chatgpt-mobile-mcp`. A live ChatGPT chat called the same tools successfully.
- ChatGPT submitted an action-review test to the shared inbox. The user answered
  it on a phone in Focus mode, producing a one-time answer receipt. ChatGPT then
  retrieved that answer, recorded completed receipt use, displayed Ready, and
  reported success. The ledger stores that outcome as agent-asserted evidence
  with calibration eligibility disabled.
- The user confirmed completing the native Claude and ChatGPT phone-app checks.
  The authenticated identity names above were verified through live browser calls
  and the corresponding OAuth grants in the ledger.

These checks cover account connections, distinct identities, and the phone
review round trip, with native phone-app checks confirmed by the user.

## Connect each account

Use the public origin of your own deployed hub and append `/mcp`. Register a
separate Switchboard identity for each account, and keep its key private.

For Claude, open **Customize → Connectors → Add custom connector** on the web.
Use OAuth authentication. If the client offers different OAuth identity modes,
this server supports automatic registration with PKCE. Enter the agent key only
on Switchboard's consent page, then enable Switchboard in the chat's connector
menu. See [Claude's current connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).

For ChatGPT, open **Plugins → + → Add custom MCP server**. Enter the hub's MCP
URL, select OAuth, create the plugin, and install it. Then select Switchboard in
a chat. See the [official plugin quickstart](https://developers.openai.com/plugins/quickstart).
The quickstart's sample server uses no authentication; Switchboard requires OAuth.

Verify with `get_connection_status` and check the expected agent name, then call
`get_rules` for a test category. Tool discovery and a saved configuration alone
do not establish authenticated access. Native phone availability depends on
the account, app version, and workspace policy.

Existing connectors that still point to the old Modal workspace must be
replaced with the current hub URL. Claude's existing connector UI may require
removing and re-adding a custom connector to change its server URL.

## Review questions on your phone

1. Open your Switchboard hub in the phone's browser and sign in to its operator
   interface. The operator login is separate from an agent's OAuth connection.
2. On **Decide**, tap **Start focus** when questions or proposals are waiting.
3. In **Questions**, review the agent, project, question, and optional context.
   Choose an offered answer or use **Allow once** / **Deny** where available.
4. Use **Later** to leave a question in the inbox. No answer is sent by that action.
5. In **Proposals**, use directions or a written request to ask for revisions.
   A steering swipe requests a change; it does not approve an action.

Simple eligible questions support horizontal swipes. Locked questions, action
reviews, and questions with answer options require deliberate taps. Focus
answers are one-time answers; the Focus interface does not save a standing rule.

After answering, return to the agent conversation and have it check the
existing question with `get_action_request_status(question_id)`. Despite its
historical name, the MCP tool supports action reviews, preferences, permissions,
and disambiguation questions. It only returns answers owned by that agent.
The agent must reuse the returned receipt, record downstream use, and report
outcomes as agent assertions. It must not submit the same question again or
treat a pending request as permission.

## A small connection test

Ask the connected agent to submit a reversible `action_review` in category
`mobile_connection_test`, using a stable request ID and the question:

> Connection test: may I display Ready for this test only?

Use explicit allow/deny options and `context.verification_only=true`. Answer it
in Focus mode, then have the same agent retrieve the answer. An allow can
authorize displaying the test label; a deny must be honored. This test does not
authorize purchases, messages, deployments, or other unrelated work.

Account connectors expose tools and server instructions. They do not install
the Claude Code or OpenCode action gates inside the native mobile apps. Those
apps must follow the ask-first protocol; [AGENTS.md](../AGENTS.md) defines it.
