import pytest

from switchboard.domain import QuestionRequest
from switchboard.persistence import Store
from switchboard.service import SwitchboardError, SwitchboardService


def make():
    svc = SwitchboardService(Store(":memory:"))
    reg = svc.register_agent("tester", "cli")
    return svc, svc.authenticate(reg["api_key"])


def queue(svc, agent, rid, **kw):
    svc.ask(agent, QuestionRequest(request_id=rid, **kw))
    return svc.inbox()[-1]


def test_reversible_single_is_swipe_eligible():
    svc, agent = make()
    item = queue(svc, agent, "r1", question="May I restart staging?", category="infra",
                 reversibility="reversible")
    assert item["swipe_eligible"] is True and item["is_locked"] is False
    out = svc.answer_inbox(item["id"], {"value": "allow"}, origin="swipe")
    assert out["decision_id"]


def test_locked_category_not_swipeable_and_swipe_rejected():
    svc, agent = make()
    item = queue(svc, agent, "r1", question="May I pay the invoice?", category="infra",
                 reversibility="reversible")
    # Locked categories defer at ask-time and never queue; lock the category
    # after queueing (operator action) to exercise the answer-path gate.
    svc.store.execute("UPDATE category_settings SET locked=1 WHERE category='infra'")
    item = svc.inbox()[-1]
    assert item["swipe_eligible"] is False and item["is_locked"] is True
    with pytest.raises(SwitchboardError):
        svc.answer_inbox(item["id"], {"value": "allow"}, origin="swipe")
    # Item stays queued; a deliberate tap answer still works.
    assert svc.inbox()
    out = svc.answer_inbox(item["id"], {"value": "allow"}, origin="tap")
    assert out["decision_id"]


def test_locked_category_question_still_reaches_human():
    # Regression: locked used to defer before queueing, so the question
    # vanished — the agent waited forever and the human never saw it.
    # Locked means "always asks you", so it must land in the inbox.
    svc, agent = make()
    resp = svc.ask(agent, QuestionRequest(
        request_id="pay1", question="May I pay the hotel $140 now?", category="payments",
        reversibility="costly"))
    assert resp["decision"] == "defer" and resp["reason_code"] == "locked"
    item = svc.inbox()[-1]
    assert item["category"] == "payments" and item["is_locked"] is True
    assert item["swipe_eligible"] is False
    out = svc.answer_inbox(item["id"], {"value": "deny"}, origin="tap")
    assert out["decision_id"]


def test_unknown_reversibility_fails_closed():
    svc, agent = make()
    item = queue(svc, agent, "r1", question="May I do a thing?", category="misc")
    assert item["reversibility"] == "unknown" and item["swipe_eligible"] is False
    with pytest.raises(SwitchboardError):
        svc.answer_inbox(item["id"], {"value": "allow"}, origin="swipe")


def test_options_questions_are_tap_only():
    svc, agent = make()
    item = queue(svc, agent, "r1", question="Which target?", category="deploy",
                 reversibility="reversible",
                 options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}])
    assert item["swipe_eligible"] is False


def test_save_rule_requires_sheet_origin_scope_and_unlocked():
    svc, agent = make()
    item = queue(svc, agent, "r1", question="May I restart staging?", category="infra",
                 reversibility="reversible")
    with pytest.raises(SwitchboardError):
        svc.answer_inbox(item["id"], {"value": "allow"}, origin="tap",
                         save_rule={"keywords": ["restart"]})
    item = queue(svc, agent, "r2", question="May I restart staging?", category="infra",
                 reversibility="reversible")
    out = svc.answer_inbox(item["id"], {"value": "allow"}, origin="rule_sheet",
                           save_rule={"keywords": ["restart"],
                                      "scope": {"mandatory": {"env": "staging"}}})
    assert out["rule"]["action"] in ("created", "superseded")


def test_save_rule_rejected_on_locked_category():
    svc, agent = make()
    item = queue(svc, agent, "r1", question="May I delete the file?", category="infra",
                 reversibility="reversible")
    svc.store.execute("UPDATE category_settings SET locked=1 WHERE category='infra'")
    item = svc.inbox()[-1]
    with pytest.raises(SwitchboardError):
        svc.answer_inbox(item["id"], {"value": "allow"}, origin="rule_sheet",
                         save_rule={"keywords": ["delete"],
                                    "scope": {"mandatory": {"env": "staging"}}})


def test_inbox_detail_returns_provenance():
    svc, agent = make()
    item = queue(svc, agent, "r1", question="May I restart staging?", category="infra",
                 reversibility="reversible")
    d = svc.inbox_detail(item["id"])
    assert d["agent"]["name"] == "tester"
    assert d["eligibility"]["swipe_eligible"] is True
    assert d["events"] and d["question"]["question_text"].startswith("May I")


def test_replay_on_resolved_item_rejected():
    svc, agent = make()
    item = queue(svc, agent, "r1", question="May I restart staging?", category="infra",
                 reversibility="reversible")
    svc.answer_inbox(item["id"], {"value": "allow"}, origin="tap")
    with pytest.raises(SwitchboardError):
        svc.answer_inbox(item["id"], {"value": "allow"}, origin="tap")
