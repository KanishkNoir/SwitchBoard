from switchboard.domain import QuestionRequest
from switchboard.persistence import Store
from switchboard.service import SwitchboardService


def make(stage="auto"):
    svc = SwitchboardService(Store(":memory:"))
    reg = svc.register_agent("tester", "cli")
    svc.create_rule("deploy",
                    {"keywords": ["deploy", "target"], "example_question": "Which deploy target?"},
                    {"option_id": "a", "value": "staging"}, scope={"mandatory": {"env": "staging"}})
    svc.set_stage("deploy", stage)
    return svc, svc.authenticate(reg["api_key"])


def answered(svc, agent, rid, label=None, human=True):
    r = svc.ask(agent, QuestionRequest(request_id=rid, question="Which deploy target?",
                                       category="deploy", context={"env": "staging"}))
    assert r["decision"] == "answer", r
    if label:
        if human:
            svc.confirm_feedback(r["decision_id"], label)
        else:
            svc.report_outcome(agent, r["decision_id"], label)
        # Drift detection (separate system) pauses the rule on negatives;
        # clear its holds so this test isolates the risk gate.
        svc.clear_holds("deploy")
    return r


def test_gate_insufficient_evidence_by_default():
    svc, _ = make()
    est = svc.risk_estimate("deploy")
    assert est["gold_sample"] == 0 and est["gate_state"] == "insufficient_evidence"
    assert est["enforced"] is False


def test_agent_labels_never_count_toward_gate():
    svc, agent = make()
    for i in range(5):
        answered(svc, agent, f"a{i}", label="failure", human=False)
    est = svc.risk_estimate("deploy")
    assert est["gold_sample"] == 0 and est["gate_state"] == "insufficient_evidence"


def test_shadow_gate_flags_but_never_blocks():
    svc, agent = make()
    for i in range(30):
        answered(svc, agent, f"b{i}", label="incorrect")
    est = svc.risk_estimate("deploy")
    assert est["gold_sample"] == 30 and est["gate_state"] == "would_block"
    assert est["wilson_upper"] > est["risk_target"]
    # Shadow mode: the next answer still goes out, flagged.
    r = answered(svc, agent, "b-next")
    assert r["risk_gate"]["would_block"] is True and r["risk_gate"]["enforced"] is False


def test_within_target_when_labels_clean():
    # 30 clean labels cannot certify a 2% target (Wilson upper ~11%); ~200 can.
    svc, agent = make()
    for i in range(200):
        answered(svc, agent, f"c{i}", label="correct")
    est = svc.risk_estimate("deploy")
    assert est["gate_state"] == "within_target" and est["errors"] == 0
    r = answered(svc, agent, "c-next")
    assert r["risk_gate"]["would_block"] is False


def test_readiness_reports_labels_needed():
    svc, agent = make()
    answered(svc, agent, "d0", label="correct")
    ready = svc.gate_readiness("deploy")
    assert ready["labels_needed"] == 29 and ready["can_enforce"] is False
