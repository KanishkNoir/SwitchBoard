import json

import httpx
from fastapi.testclient import TestClient

import switchboard.app as app_module
from switchboard.domain import QuestionRequest
from switchboard.onboard import AGENTS, render
from switchboard.remote import HubClient


def _client(handler):
    return HubClient("https://hub.example", "sb_key123", transport=httpx.MockTransport(handler))


def test_hub_ask_posts_with_agent_key_and_maps_fields():
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("x-agent-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"decision": "defer", "question_id": "q1"})

    out = _client(handler).ask(QuestionRequest(
        request_id="r1", question="ok?", category="git", reversibility="costly"))
    assert out["decision"] == "defer" and out["question_id"] == "q1"
    assert seen["key"] == "sb_key123"
    assert seen["body"]["request_id"] == "r1" and seen["body"]["reversibility"] == "costly"


def test_hub_unreachable_fails_closed_to_defer():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    hub = _client(handler)
    out = hub.ask(QuestionRequest(request_id="r1", question="ok?", category="git"))
    assert out["decision"] == "defer" and out["reason_code"] == "hub_unreachable"
    assert hub.get_rules() == []
    assert hub.report_outcome("d1", "done")["recorded"] is False
    assert hub.record_use("rc1", "task", "t1")["recorded"] is False


def test_onboard_remote_env_in_all_stdio_configs():
    for name in AGENTS:
        _, content = render(name, "sb_x", "stdio", remote="https://hub.example")
        assert "SWITCHBOARD_REMOTE_URL" in content, name
        assert "hub.example" in content, name


def test_registration_requires_ui_token_when_set(monkeypatch):
    monkeypatch.setattr(app_module, "UI_TOKEN", "tok-1")
    client = TestClient(app_module.app)
    assert client.post("/api/agents/register", json={"name": "x"}).status_code == 401
    r = client.post("/api/agents/register", json={"name": "hubtest"},
                    headers={"x-ui-token": "tok-1"})
    assert r.status_code == 200 and r.json()["api_key"].startswith("sb_")
