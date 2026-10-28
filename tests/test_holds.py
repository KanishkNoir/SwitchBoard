"""V1 sliced recalibration hold — the five audit-specified production tests."""
from switchboard.domain import QuestionRequest
from switchboard.persistence import Store
from switchboard.service import SwitchboardService


def make():
    svc = SwitchboardService(Store(":memory:"))
    reg = svc.register_agent("tester", "cli")
    return svc, svc.authenticate(reg["api_key"])


def seed_two_rules(svc):
    svc.create_rule("purchase", {"keywords": ["deploy", "target"]}, {"value": "staging"},
                    scope={"mandatory": {"env": "staging"}})
    svc.create_rule("purchase", {"keywords": ["notify", "channel"]}, {"value": "email"},
                    scope={"mandatory": {"team": "core"}})
    svc.set_stage("purchase", "auto")


def ask(svc, agent, rid, q, ctx):
    return svc.ask(agent, QuestionRequest(request_id=rid, question=q, category="purchase",
                                          intent_type="preference", context=ctx))


def flip_deploy_rule(svc):
    rid = svc.store.query_one(
        "SELECT rule_id FROM rule_versions rv JOIN rules r ON r.id=rv.rule_id"
        " WHERE rv.answer_json LIKE '%staging%'")["rule_id"]
    return svc.supersede_rule(rid, new_answer={"value": "canary"})


def test_hold_clears_via_distinct_human_answer_inbox():
    svc, agent = make()
    seed_two_rules(svc)
    flip_deploy_rule(svc)
    r = ask(svc, agent, "h1", "Which deploy target?", {"env": "staging"})
    assert r["decision"] == "defer" and r["reason_code"] == "recalibration_pending"
    item = next(i for i in svc.inbox() if i["question_id"] == r["question_id"])
    svc.answer_inbox(item["id"], {"value": "canary"})
    r2 = ask(svc, agent, "h2", "Which deploy target?", {"env": "staging"})
    assert r2["decision"] == "answer" and r2["answer"]["value"] == "canary"


def test_agent_labels_never_release_hold():
    svc, agent = make()
    seed_two_rules(svc)
    flip_deploy_rule(svc)
    r = ask(svc, agent, "a1", "Which deploy target?", {"env": "staging"})
    svc.report_outcome(agent, r["decision_id"], "success", "agent claims fine")
    svc.report_outcome(agent, r["decision_id"], "success", "agent claims again")
    r2 = ask(svc, agent, "a2", "Which deploy target?", {"env": "staging"})
    assert r2["decision"] == "defer" and r2["reason_code"] == "recalibration_pending"


def test_duplicate_context_does_not_farm_m():
    # Semantic-only rule requires m=3 distinct contexts.
    svc, agent = make()
    svc.create_rule("purchase", {"example_question": "preferred deployment destination"},
                    {"value": "staging"})
    svc.set_stage("purchase", "auto")
    rid = svc.store.query_one("SELECT id FROM rules WHERE category='purchase'")["id"]
    svc.supersede_rule(rid, new_answer={"value": "canary"})
    holds = svc.list_holds("purchase")
    assert holds and holds[0]["required_m"] == 3
    for i in range(3):
        svc._record_fresh_evidence("purchase", {"env": "staging"}, "answer_inbox")
    assert svc.list_holds("purchase")[0]["fresh_count"] == 1  # same context counted once
    svc._record_fresh_evidence("purchase", {"env": "staging", "team": "core"}, "answer_inbox")
    svc._record_fresh_evidence("purchase", {"env": "staging", "team": "edge"}, "answer_inbox")
    assert svc.list_holds("purchase")[0]["status"] == "released"


def test_unrelated_slice_in_same_category_still_answers():
    svc, agent = make()
    seed_two_rules(svc)
    flip_deploy_rule(svc)
    r = ask(svc, agent, "u1", "Which notify channel?", {"team": "core"})
    assert r["decision"] == "answer" and r["answer"]["value"] == "email"


def test_passport_shows_held_slice_and_note():
    svc, agent = make()
    seed_two_rules(svc)
    flip_deploy_rule(svc)
    p = svc.passport("purchase")
    assert p["held_slices"] == 1 and "smoke-test" in p["hold_note"]
