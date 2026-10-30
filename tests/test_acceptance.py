"""Spec §12.4 acceptance, encoded: preference stated once inside a scope is
reused inside that scope, a correction supersedes it, and the corrected
preference does not leak into an unrelated context."""
from switchboard.domain import QuestionRequest
from switchboard.persistence import Store
from switchboard.service import SwitchboardService


def test_preference_reuse_correction_and_scope_containment():
    svc = SwitchboardService(Store(":memory:"))
    reg = svc.register_agent("travel-agent", "assistant")
    agent = svc.authenticate(reg["api_key"])

    # 1. No rule yet: the question comes to the human.
    r1 = svc.ask(agent, QuestionRequest(
        request_id="a1", question="Which hotel area should I book?",
        category="travel", context={"branch": "NYC"}, reversibility="costly"))
    assert r1["decision"] == "defer"

    # 2. Human answers once and makes it a rule, scoped to the NYC branch.
    item = svc.inbox()[0]
    svc.answer_inbox(item["id"], {"value": "Midtown"}, origin="rule_sheet",
                     save_rule={"keywords": ["hotel", "area"],
                                "scope": {"mandatory": {"branch": "NYC"}}})
    svc.set_stage("travel", "auto")

    # 3. Same decision, same scope: answered from the preference, no human needed.
    r2 = svc.ask(agent, QuestionRequest(
        request_id="a2", question="Which hotel area should I book?",
        category="travel", context={"branch": "NYC"}, reversibility="costly"))
    assert r2["decision"] == "answer" and r2["answer"]["value"] == "Midtown"

    # 4. Correction: the human supersedes the preference.
    rule = svc.list_rules_human("travel")[0]
    svc.supersede_rule(rule["rule_id"], new_answer={"value": "Downtown"})
    svc.clear_holds("travel")  # human releases recalibration after reviewing

    r3 = svc.ask(agent, QuestionRequest(
        request_id="a3", question="Which hotel area should I book?",
        category="travel", context={"branch": "NYC"}, reversibility="costly"))
    assert r3["decision"] == "answer" and r3["answer"]["value"] == "Downtown"

    # 5. Unrelated context: the preference must NOT apply; the human is asked.
    r4 = svc.ask(agent, QuestionRequest(
        request_id="a4", question="Which hotel area should I book?",
        category="travel", context={"branch": "LA"}, reversibility="costly"))
    assert r4["decision"] == "defer"
