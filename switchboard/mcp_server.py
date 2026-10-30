"""MCP ingress (LLD 6.1-6.4). Agent identity comes from SWITCHBOARD_AGENT_KEY, never payload JSON."""
import os

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from .config import settings
from .domain import QuestionRequest
from .persistence import Store
from .service import SwitchboardService

mcp = FastMCP("switchboard")
_svc = None
_hub = None


def svc() -> SwitchboardService:
    global _svc
    if _svc is None:
        _svc = SwitchboardService(Store(settings.db_path))
    return _svc


def hub():
    """Device-agnostic mode: proxy to the hub API when SWITCHBOARD_REMOTE_URL is set."""
    global _hub
    if _hub is None and settings.remote_url:
        from .remote import HubClient
        _hub = HubClient(settings.remote_url, os.environ.get("SWITCHBOARD_AGENT_KEY", ""))
    return _hub


def _agent():
    return svc().authenticate(os.environ.get("SWITCHBOARD_AGENT_KEY", ""))


@mcp.tool()
def ask(request_id: str, question: str, category: str, intent_type: str = "unknown",
        reversibility: str = "unknown", context: dict | None = None, options: list | None = None) -> dict:
    """Ask Switchboard whether a question is already answered by a valid user rule."""
    req = QuestionRequest(
        request_id=request_id, question=question, category=category, intent_type=intent_type,
        reversibility=reversibility, context=context or {}, options=options or [])
    if hub() is not None:
        return hub().ask(req)
    return svc().ask(_agent(), req)


@mcp.tool()
def submit_proposal(title: str, proposal_text: str, category: str, directions: list) -> dict:
    """Submit a steerable proposal: your draft plus 2-4 directions you can move in.

    Each direction: {"edge": "top|left|right|bottom", "label": "Cheaper",
    "expected_effect": "what changes if the human steers this way"}.
    The human steers from Switchboard; steering never accepts your proposal.
    Poll get_steering for nudges, answer with revise_proposal, and stop when
    get_steering reports accepted/rejected.
    """
    if hub() is not None:
        return hub().submit_proposal(title, proposal_text, category, directions)
    return svc().submit_proposal(_agent(), title, proposal_text, category, directions)


@mcp.tool()
def get_steering(session_id: str) -> dict:
    """Poll for the human's latest steer (or final acceptance) on your proposal."""
    if hub() is not None:
        return hub().pending_steer(session_id)
    return svc().pending_steer(_agent(), session_id)


@mcp.tool()
def revise_proposal(session_id: str, proposal_text: str, note: str = "") -> dict:
    """Answer a steer with a revised version of your proposal."""
    if hub() is not None:
        return hub().revise_proposal(session_id, proposal_text, note or None)
    return svc().revise_proposal(_agent(), session_id, proposal_text, note or None)


@mcp.tool()
def get_rules(category: str | None = None) -> list:
    """List active user rules this agent may read (read-only)."""
    if hub() is not None:
        return hub().get_rules(category)
    return svc().get_rules(_agent(), category)


@mcp.tool()
def report_outcome(decision_id: str, outcome: str, detail: str = "") -> dict:
    """Report an outcome; stored as agent_asserted evidence, never a gold label."""
    if hub() is not None:
        return hub().report_outcome(decision_id, outcome, detail)
    return svc().report_outcome(_agent(), decision_id, outcome, detail)


@mcp.tool()
def record_use(receipt_id: str, dependent_type: str, dependent_id: str,
               relationship: str = "used_answer", status: str = "pending") -> dict:
    """Record that a prior receipt influenced downstream work (best-effort dependency edge)."""
    if hub() is not None:
        return hub().record_use(receipt_id, dependent_type, dependent_id, relationship, status)
    return svc().record_use(_agent(), receipt_id, dependent_type, dependent_id, relationship, status)


if __name__ == "__main__":
    # stdio (default, one agent per process) or streamable-http (local network demo).
    # For HTTP, the server operator sets SWITCHBOARD_AGENT_KEY to the registered
    # agent's key; identity is server-side, never taken from payload JSON.
    transport = os.environ.get("SWITCHBOARD_MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.run(transport="streamable-http",
                host=os.environ.get("SWITCHBOARD_MCP_HOST", "127.0.0.1"),
                port=int(os.environ.get("SWITCHBOARD_MCP_PORT", "8766")))
    else:
        mcp.run(transport="stdio")
