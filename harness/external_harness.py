"""External harness demo: a separate process that talks to Switchboard ONLY via MCP.

This simulates a real compatible agent (e.g. a CLI coding agent) that:
  1. asks Switchboard before asking its human,
  2. records downstream use of the receipt,
  3. reports its outcome (stored as agent_asserted, never a gold label).

Run the backend first, register an agent, then:

  # stdio transport
  SWITCHBOARD_AGENT_KEY=sb_... uv run python harness/external_harness.py

  # streamable-http transport (start the MCP HTTP server separately with the same key)
  SWITCHBOARD_AGENT_KEY=sb_... SWITCHBOARD_MCP_TRANSPORT=streamable-http \
      uv run python -m switchboard.mcp_server
  uv run python harness/external_harness.py --transport http
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    ap.add_argument("--url", default="http://127.0.0.1:8766/mcp")
    ap.add_argument("--question", default="Which deploy target should I use?")
    ap.add_argument("--category", default="purchase")
    ap.add_argument("--env", default="staging")
    args = ap.parse_args()

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    if args.transport == "http":
        from mcp.client.streamable_http import streamable_http_client

        ctx = streamable_http_client(args.url)
    else:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "switchboard.mcp_server"],
            env={**os.environ},
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        ctx = stdio_client(params)

    async with ctx as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])

            async def ask(rid: str):
                res = await session.call_tool("ask", {
                    "request_id": rid, "question": args.question, "category": args.category,
                    "intent_type": "preference", "context": {"env": args.env}})
                return json.loads(res.content[0].text)

            first = await ask("harness-1")
            print("ask 1:", first["decision"], first["reason_code"], first.get("answer"))
            second = await ask("harness-2")
            print("ask 2 (repeat):", second["decision"], second["reason_code"], second.get("answer"))

            receipt = second.get("receipt_id") or first.get("receipt_id")
            if receipt:
                use = await session.call_tool("record_use", {
                    "receipt_id": receipt, "dependent_type": "task",
                    "dependent_id": "deploy-task-42", "relationship": "used_answer"})
                print("record_use:", use.content[0].text[:120])
            dec = second.get("decision_id") or first.get("decision_id")
            if dec:
                out = await session.call_tool("report_outcome", {
                    "decision_id": dec, "outcome": "success",
                    "detail": "deploy playbook ran (agent self-report)"})
                print("report_outcome:", out.content[0].text[:160])
            return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
