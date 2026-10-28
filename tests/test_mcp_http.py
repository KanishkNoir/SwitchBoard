"""Integration: real MCP client <-> Switchboard over Streamable HTTP (Stage 9)."""
import asyncio
import json
import os
import subprocess
import sys
import time

import httpx
import pytest


def _free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.skipif(os.environ.get("SWITCHBOARD_IT") != "1",
                    reason="set SWITCHBOARD_IT=1 (spawns a real MCP HTTP server subprocess)")
def test_mcp_streamable_http_end_to_end(tmp_path):
    # Seed the shared DB in-process; the MCP server subprocess reads the same file.
    from switchboard.persistence import Store
    from switchboard.service import SwitchboardService
    svc = SwitchboardService(Store(str(tmp_path / "it.db")))
    reg = svc.register_agent("it-agent", "cli")
    svc.create_rule("purchase", {"keywords": ["deploy", "target"]}, {"value": "staging"},
                    scope={"mandatory": {"env": "staging"}})
    svc.set_stage("purchase", "auto")
    mcp_proc = None
    try:

        port = _free_port()
        mcp_proc = subprocess.Popen(
            [sys.executable, "-m", "switchboard.mcp_server"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            env={**os.environ, "SWITCHBOARD_AGENT_KEY": reg["api_key"],
                 "SWITCHBOARD_MCP_TRANSPORT": "streamable-http",
                 "SWITCHBOARD_MCP_PORT": str(port),
                 "SWITCHBOARD_DB": str(tmp_path / "it.db")},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        async def run():
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
            url = f"http://127.0.0.1:{port}/mcp"
            last = None
            for _ in range(50):
                try:
                    async with streamable_http_client(url) as streams:
                        async with ClientSession(streams[0], streams[1]) as session:
                            await session.initialize()
                            tools = await session.list_tools()
                            assert {t.name for t in tools.tools} >= {"ask", "get_rules",
                                                                      "report_outcome", "record_use"}
                            res = await session.call_tool("ask", {
                                "request_id": "it-1", "question": "Which deploy target?",
                                "category": "purchase", "intent_type": "preference",
                                "context": {"env": "staging"}})
                            return json.loads(res.content[0].text)
                except Exception as e:  # server not up yet
                    last = e
                    await asyncio.sleep(0.3)
            raise AssertionError(f"MCP HTTP server never answered: {last}")

        out = asyncio.run(run())
        assert out["decision"] == "answer" and out["answer"]["value"] == "staging"
    finally:
        if mcp_proc:
            mcp_proc.terminate()
