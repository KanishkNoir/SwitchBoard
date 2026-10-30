from switchboard.domain import QuestionRequest
from switchboard.persistence import Store
from switchboard.service import SwitchboardService


def make():
    svc = SwitchboardService(Store(":memory:"))
    reg = svc.register_agent("tester", "cli")
    return svc, svc.authenticate(reg["api_key"])


def test_debrief_explains_human_answer_with_origin():
    svc, agent = make()
    svc.ask(agent, QuestionRequest(request_id="r1", question="May I restart staging?",
                                   category="infra", reversibility="reversible"))
    item = svc.inbox()[0]
    svc.answer_inbox(item["id"], {"value": "allow"}, origin="swipe", dwell_ms=1200)
    rows = svc.debrief()
    top = next(r for r in rows if r["question_text"] == "May I restart staging?")
    assert top["bucket"] == "answered_by_you" and top["origin"] == "swipe"
    assert top["dwell_ms"] == 1200 and top["receipt_id"]
    assert top["reason_plain"] and top["reason_plain"] != top["reason_code"]


def test_debrief_buckets_auto_and_waiting():
    svc, agent = make()
    svc.create_rule("deploy", {"keywords": ["deploy", "target"],
                               "example_question": "Which deploy target?"},
                    {"value": "staging"}, scope={"mandatory": {"env": "staging"}})
    svc.set_stage("deploy", "auto")
    svc.ask(agent, QuestionRequest(request_id="r1", question="Which deploy target?",
                                   category="deploy", context={"env": "staging"}))
    svc.ask(agent, QuestionRequest(request_id="r2", question="Unrelated ask?",
                                   category="misc", reversibility="costly"))
    by_q = {r["question_text"]: r for r in svc.debrief()}
    assert by_q["Which deploy target?"]["bucket"] == "auto_answered"
    assert by_q["Unrelated ask?"]["bucket"] == "still_waiting"


def test_debrief_denial_bucket():
    svc, agent = make()
    svc.ask(agent, QuestionRequest(request_id="r1", question="May I send it?",
                                   category="messaging", reversibility="reversible"))
    svc.answer_inbox(svc.inbox()[0]["id"], {"value": "deny"}, origin="tap")
    assert svc.debrief()[0]["bucket"] == "denied_by_you"
