"""MCP ingress (LLD 6.1-6.4). Agent identity comes from SWITCHBOARD_AGENT_KEY, never payload JSON."""
import os

from pydantic import AnyHttpUrl
from mcp.server.mcpserver import MCPServer as FastMCP
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions

from .config import settings
from .domain import QuestionRequest
from .persistence import Store
from .service import SwitchboardService
from .mcp_auth import SwitchboardOAuthProvider

_svc = None
_hub = None
_force_local_backend = False
_oauth_provider = None
_public_url = os.environ.get("SWITCHBOARD_MCP_PUBLIC_URL", "").rstrip("/")


def _make_mcp():
    global _oauth_provider
    if not _public_url:
        return FastMCP("switchboard")
    _oauth_provider = SwitchboardOAuthProvider(
        svc().store, _public_url, lambda key: svc().authenticate(key))
    return FastMCP(
        "switchboard",
        auth_server_provider=_oauth_provider,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(_public_url),
            resource_server_url=AnyHttpUrl(_public_url + "/mcp"),
            validate_token_resource=True,
            required_scopes=["switchboard:access"],
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["switchboard:access"],
                default_scopes=["switchboard:access"],
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
    )


def svc() -> SwitchboardService:
    global _svc
    if _svc is None:
        _svc = SwitchboardService(Store(settings.db_path))
    return _svc


mcp = _make_mcp()


def bind_service(service: SwitchboardService) -> None:
    """Share the web app's store when MCP is mounted in the same Modal worker."""
    global _svc
    _svc = service
    if _oauth_provider is not None:
        _oauth_provider.store = service.store


def use_local_backend() -> None:
    """Keep hosted MCP calls on this Modal worker's shared ledger."""
    global _force_local_backend
    _force_local_backend = True


def hub():
    """Device-agnostic mode: proxy to the hub API when SWITCHBOARD_REMOTE_URL is set."""
    global _hub
    if _force_local_backend:
        return None
    if _hub is None and settings.remote_url:
        from .remote import HubClient
        _hub = HubClient(settings.remote_url, os.environ.get("SWITCHBOARD_AGENT_KEY", ""))
    return _hub


def _agent():
    token = get_access_token()
    if token is not None and token.subject:
        return svc().authenticate_agent_id(token.subject)
    return svc().authenticate(os.environ.get("SWITCHBOARD_AGENT_KEY", ""))


if _oauth_provider is not None:
    from starlette.requests import Request
    from starlette.responses import Response

    @mcp.custom_route("/oauth/consent", methods=["GET", "POST"], include_in_schema=False)
    async def oauth_consent(request: Request) -> Response:
        return await _oauth_provider.consent_page(request)


def hosted_http_app():
    """Build the remote MCP ASGI app used by Modal when OAuth is configured."""
    if not _public_url:
        raise RuntimeError("SWITCHBOARD_MCP_PUBLIC_URL is required for hosted MCP")
    if not _public_url.startswith("https://"):
        raise RuntimeError("Hosted MCP requires a public HTTPS base URL")
    return mcp.streamable_http_app(streamable_http_path="/mcp", host="0.0.0.0")


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
def submit_proposal(title: str, proposal_text: str, category: str, directions: list,
                    project: str = "") -> dict:
    """Submit a steerable proposal: your draft plus 2-4 directions you can move in.

    Each direction: {"edge": "top|left|right|bottom", "label": "Cheaper",
    "expected_effect": "what changes if the human steers this way"}.
    The human steers from Switchboard; steering never accepts your proposal.
    Poll get_steering for nudges, answer with revise_proposal, and stop when
    get_steering reports accepted/rejected.
    """
    if hub() is not None:
        return hub().submit_proposal(title, proposal_text, category, directions, project or None)
    return svc().submit_proposal(_agent(), title, proposal_text, category, directions,
                                 project=project or None)


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
def get_action_request_status(question_id: str) -> dict:
    """Check whether the user answered this agent's queued action review."""
    if hub() is not None:
        return hub().action_request_status(question_id)
    return svc().action_request_status(_agent(), question_id)


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
