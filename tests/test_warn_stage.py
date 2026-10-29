from switchboard.domain import QuestionRequest
from switchboard.persistence import Store
from switchboard.service import SwitchboardService


def make(stage="warn"):
    svc = SwitchboardService(Store(":memory:"))
    reg = svc.register_agent("tester", "cli")
    svc.create_rule("deploy",
                    {"keywords": ["deploy", "target"], "example_question": "Which deploy target?"},
                    {"option_id": "a", "value": "staging"}, scope={"mandatory": {"env": "staging"}})
    svc.set_stage("deploy", stage)
    return svc, svc.authenticate(reg["api_key"])


def ask(svc, agent, rid):
    return svc.ask(agent, QuestionRequest(request_id=rid, question="Which deploy target?",
                                          category="deploy", context={"env": "staging"}))


def test_warn_stage_answers_but_warns_and_notifies():
    svc, agent = make()
    r = ask(svc, agent, "r1")
    assert r["decision"] == "answer" and r["answer"]["value"] == "staging"
    assert r["stage"] == "warn" and r.get("warning")
    assert r["requires_human"] is False
    notices = svc.notices()
    assert len(notices) == 1 and notices[0]["question_text"] == "Which deploy target?"
    assert svc.inbox() == []  # warned answers are notices, not questions waiting


def test_veto_records_human_negative_and_clears_notice():
    svc, agent = make()
    ask(svc, agent, "r1")
    notice = svc.notices()[0]
    out = svc.veto_notice(notice["id"])
    assert out["vetoed"] is True
    assert svc.notices() == []
    row = svc.detect_drift()[0]
    assert row["human_negatives"] == 1 and row["status"] == "watch"


def test_warn_without_match_still_defers():
    svc, agent = make()
    r = svc.ask(agent, QuestionRequest(request_id="r9", question="What is the wifi password?",
                                       category="deploy", context={"env": "staging"}))
    assert r["decision"] == "defer"
    assert svc.notices() == [] and len(svc.inbox()) == 1


def test_auto_stage_creates_no_notice():
    svc, agent = make(stage="auto")
    r = ask(svc, agent, "r1")
    assert r["decision"] == "answer" and not r.get("warning")
    assert svc.notices() == []
