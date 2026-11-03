"""Credential transport and real connectivity, rather than discovery alone."""
from contextlib import asynccontextmanager
import json

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import httpx
import pytest

from switchboard.credentials import agent_key
from switchboard.hosting import combined_app
from switchboard.remote import HubClient, HubUnavailableError


def test_agent_key_can_be_kept_out_of_project_config(tmp_path):
    private = tmp_path / "agent.key"
    private.write_text("sb_private-test\n", encoding="utf-8")
    assert agent_key({"SWITCHBOARD_AGENT_KEY_FILE": str(private)}) == "sb_private-test"
    assert agent_key({"SWITCHBOARD_AGENT_KEY": "${SWITCHBOARD_AGENT_KEY}",
                      "SWITCHBOARD_AGENT_KEY_FILE": str(private)}) == "sb_private-test"
    assert agent_key({"SWITCHBOARD_AGENT_KEY": "sb_override", "SWITCHBOARD_AGENT_KEY_FILE": str(private)}) == "sb_override"
    assert agent_key({"SWITCHBOARD_AGENT_KEY_FILE": str(tmp_path / "missing")}) == ""
    assert agent_key({"SWITCHBOARD_AGENT_KEY": "sb_REPLACE_ME"}) == ""


@pytest.mark.parametrize("status", [401, 403, 404, 503])
def test_failed_hub_lookup_cannot_look_like_an_empty_rule_set(status):
    hub = HubClient("https://hub.test", "unused", transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json={"error": "unavailable"})))
    with pytest.raises(HubUnavailableError):
        hub.get_rules()
    assert hub.connection_status() == {"connected": False, "backend": "hub",
                                       "reason_code": "hub_http_error", "http_status": status}


def test_healthy_empty_rules_and_authenticated_connection_are_distinct():
    def handler(request):
        assert request.headers["x-agent-key"] == "sb_test"
        data = {"/health": {"status": "ok", "version": "test", "build_id": "build-test"},
                "/api/identity": {"id": "one", "name": "codex", "kind": "cli", "scopes": ["get_rules"]},
                "/api/rules": []}[request.url.path]
        return httpx.Response(200, json=data)
    hub = HubClient("https://hub.test", "sb_test", transport=httpx.MockTransport(handler))
    assert hub.get_rules() == []
    result = hub.connection_status()
    assert result["connected"] is True and result["agent"]["name"] == "codex"
    assert result["build_id"] == "build-test"


def test_invalid_success_response_is_not_a_connection():
    hub = HubClient("https://hub.test", "unused", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ok": True})))
    assert hub.connection_status()["connected"] is False
    with pytest.raises(HubUnavailableError):
        hub.get_rules()


def test_identity_exposes_only_the_authenticated_principal(monkeypatch):
    import switchboard.app as app_module
    from switchboard.persistence import Store
    from switchboard.service import SwitchboardService
    store = Store(":memory:")
    service = SwitchboardService(store)
    registration = service.register_agent("dedicated-codex", scopes=["get_rules"])
    monkeypatch.setattr(app_module, "svc", service)
    client = TestClient(app_module.app)
    assert client.get("/api/identity").status_code == 401
    result = client.get("/api/identity", headers={"x-agent-key": registration["api_key"]}).json()
    assert result == {"id": registration["agent_id"], "name": "dedicated-codex", "kind": "cli", "scopes": ["get_rules"]}
    assert registration["api_key"] not in json.dumps(result)
    store.close()


def test_hosted_oauth_routes_bypass_only_the_operator_ui_gate():
    web, mcp = FastAPI(), FastAPI()
    entered = []

    @web.middleware("http")
    async def gate(request, call_next):
        return JSONResponse({"error": "operator_login_required"}, status_code=401)

    @mcp.get("/{path:path}")
    def oauth_route(path):
        return {"mcp_route": path}

    class Sessions:
        @asynccontextmanager
        async def run(self):
            entered.append("started")
            yield
            entered.append("stopped")

    with TestClient(combined_app(web, mcp, Sessions())) as client:
        for path in ("/mcp", "/.well-known/oauth-authorization-server",
                     "/.well-known/oauth-protected-resource/mcp", "/authorize", "/token",
                     "/register", "/revoke", "/oauth/consent"):
            assert client.get(path).status_code == 200
        assert client.get("/human/agents").status_code == 401
    assert entered == ["started", "stopped"]


def test_public_oauth_revocation_accepts_omitted_optional_secret():
    """An RFC 7009 public client has no secret; retain confidential secrets."""
    from contextlib import asynccontextmanager
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from mcp.server.auth.handlers.revoke import RevocationRequest
    from switchboard.hosting import combined_app

    web, mcp_app = FastAPI(), FastAPI()

    @mcp_app.post("/revoke")
    async def revoke(request: Request):
        fields = dict(await request.form())
        value = RevocationRequest.model_validate(fields)
        return {"secret": value.client_secret, "token": value.token}

    class Sessions:
        @asynccontextmanager
        async def run(self):
            yield

    with TestClient(combined_app(web, mcp_app, Sessions())) as client:
        for fields, expected in [({"token": "test-token", "client_id": "public"}, ""),
                                 ({"token": "test-token", "client_id": "private", "client_secret": "test-secret"}, "test-secret")]:
            response = client.post("/revoke", data=fields)
            assert response.status_code == 200
            assert response.json() == {"secret": expected, "token": "test-token"}
