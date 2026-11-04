"""Focus answers must reach every question type without crossing identities."""
import httpx
import pytest

from switchboard.config import Settings
from switchboard.domain import QuestionRequest
from switchboard.persistence import Store
from switchboard.remote import HubClient
from switchboard.service import SwitchboardError, SwitchboardService


@pytest.mark.parametrize("intent", ["preference", "permission", "disambiguation", "action_review"])
def test_mcp_can_resume_an_owned_focus_answer_for_every_intent(intent, monkeypatch):
    import switchboard.mcp_server as server

    store = Store(":memory:")
    service = SwitchboardService(store, cfg=Settings(enable_t3=False))
    owner = service.authenticate(service.register_agent("mobile-owner")["api_key"])
    other = service.authenticate(service.register_agent("other-client")["api_key"])
    monkeypatch.setattr(server, "svc", lambda: service)
    monkeypatch.setattr(server, "hub", lambda: None)
    monkeypatch.setattr(server, "_agent", lambda: owner)
    try:
        question = service.ask(owner, QuestionRequest(
            request_id="focus-" + intent, question="Show Ready for this connection test?",
            category="mobile_test", intent_type=intent, reversibility="reversible",
            options=[{"id": "allow", "label": "Ready"}, {"id": "deny", "label": "Wait"}]))
        question_id = question["question_id"]
        assert server.get_action_request_status(question_id) == {"status": "pending", "question_id": question_id}
        item = next(item for item in service.inbox() if item["question_id"] == question_id)
        service.answer_inbox(item["id"], {"value": "allow"}, origin="tap")
        answer = server.get_action_request_status(question_id)
        assert answer["status"] == "answered" and answer["answer"]["value"] == "allow"
        assert answer["receipt_id"] and answer["decision_id"]
        monkeypatch.setattr(server, "_agent", lambda: other)
        with pytest.raises(SwitchboardError) as error:
            server.get_action_request_status(question_id)
        assert error.value.code == "NOT_FOUND"
    finally:
        store.close()


def test_remote_mcp_poll_uses_generic_question_route_and_remains_authenticated(monkeypatch):
    import switchboard.mcp_server as server

    def respond(request):
        assert request.url.path == "/api/questions/owned-question/answer"
        assert request.headers["x-agent-key"] == "synthetic-test-key"
        return httpx.Response(200, json={"status": "answered", "answer": {"value": "allow"},
                                        "receipt_id": "test-receipt", "decision_id": "test-decision"})
    hub = HubClient("https://hub.example", "synthetic-test-key", transport=httpx.MockTransport(respond))
    monkeypatch.setattr(server, "hub", lambda: hub)
    assert server.get_action_request_status("owned-question")["receipt_id"] == "test-receipt"


def test_remote_question_poll_failure_never_returns_an_answer():
    hub = HubClient("https://hub.example", "unused", transport=httpx.MockTransport(
        lambda request: httpx.Response(403, json={"error": "NOT_FOUND"})))
    assert hub.question_answer_status("other-agent-question") == {
        "status": "unavailable", "question_id": "other-agent-question", "reason_code": "hub_unreachable"}
