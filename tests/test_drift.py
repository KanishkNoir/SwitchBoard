from switchboard.domain import QuestionRequest
from switchboard.persistence import Store
from switchboard.service import SwitchboardService


def make():
    svc = SwitchboardService(Store(":memory:"))
    reg = svc.register_agent("tester", "cli")
    svc.create_rule("deploy",
                    {"keywords": ["deploy", "target"], "example_question": "Which deploy target?"},
                    {"option_id": "a", "value": "staging"}, scope={"mandatory": {"env": "staging"}})
    svc.set_stage("deploy", "auto")
    return svc, svc.authenticate(reg["api_key"])


def ask_auto(svc, agent, rid):
    r = svc.ask(agent, QuestionRequest(request_id=rid, question="Which deploy target?",
                                       category="deploy", context={"env": "staging"}))
    assert r["decision"] != "defer", r
    return r


def test_no_labels_no_drift():
    svc, _ = make()
    rows = svc.detect_drift()
    assert rows and rows[0]["status"] == "ok" and rows[0]["labelled"] == 0


def test_human_negatives_trigger_hold_and_pause_rule():
    svc, agent = make()
    r1 = ask_auto(svc, agent, "r1")
    svc.confirm_feedback(r1["decision_id"], "incorrect")
    assert svc.detect_drift()[0]["status"] == "watch"
    r2 = ask_auto(svc, agent, "r2")
    svc.confirm_feedback(r2["decision_id"], "incorrect")
    row = svc.detect_drift()[0]
    assert row["status"] == "drift_suspected" and row["human_negatives"] == 2
    # The rule is now held: the next matching question defers instead of auto-answering.
    r3 = svc.ask(agent, QuestionRequest(request_id="r3", question="Which deploy target?",
                                        category="deploy", context={"env": "staging"}))
    assert r3["decision"] == "defer" and r3["reason_code"] == "recalibration_pending"
    # Idempotent: rescanning does not stack duplicate holds.
    assert svc.detect_drift()[0]["hold_created"] is False
    assert len([h for h in svc.list_holds("deploy") if h["status"] == "held"]) == 1


def test_agent_asserted_flood_needs_volume_and_no_positives():
    svc, agent = make()
    r1 = ask_auto(svc, agent, "r1")
    svc.report_outcome(agent, r1["decision_id"], "failure")
    svc.report_outcome(agent, r1["decision_id"], "failure")
    assert svc.detect_drift()[0]["status"] == "watch"  # only 2 negatives
    svc.report_outcome(agent, r1["decision_id"], "failure")
    row = svc.detect_drift()[0]
    assert row["status"] == "drift_suspected" and row["human_negatives"] == 0


def test_positives_counter_agent_negatives():
    svc, agent = make()
    r1 = ask_auto(svc, agent, "r1")
    for _ in range(3):
        svc.report_outcome(agent, r1["decision_id"], "failure")
    svc.report_outcome(agent, r1["decision_id"], "success")
    row = svc.detect_drift()[0]
    assert row["status"] == "watch" and row["positives"] == 1
