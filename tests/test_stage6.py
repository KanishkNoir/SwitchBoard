from switchboard.domain import QuestionRequest
from switchboard.persistence import Store
from switchboard.service import SwitchboardService


def make():
    svc = SwitchboardService(Store(":memory:"))
    reg = svc.register_agent("tester", "cli")
    return svc, svc.authenticate(reg["api_key"])


def test_list_agents_and_rules():
    svc, _ = make()
    svc.create_rule("purchase", {"keywords": ["deploy"]}, {"value": "staging"})
    agents = svc.list_agents()
    assert agents and agents[0]["name"] == "tester" and "key_hash" not in agents[0]
    rules = svc.list_rules_human("purchase")
    assert len(rules) == 1 and rules[0]["version_number"] == 1
    versions = svc.rule_versions(rules[0]["rule_id"])
    assert len(versions) == 1


def test_inbox_answer_creates_decision_and_rule_then_reuse():
    svc, agent = make()
    # Shadow stage: question defers and lands in inbox.
    svc.ask(agent, QuestionRequest(request_id="q1", question="Which deploy target should I use?",
                                   category="purchase", intent_type="preference",
                                   context={"env": "staging"}))
    items = svc.inbox()
    assert items
    out = svc.answer_inbox(items[0]["id"], "staging",
                           save_rule={"keywords": ["deploy", "target"],
                                      "scope": {"mandatory": {"env": "staging"}}})
    assert out["decision_id"] and out["rule"]["action"] == "created"
    # Promote to auto: the learned rule now answers without the human.
    svc.set_stage("purchase", "auto")
    r = svc.ask(agent, QuestionRequest(request_id="q2", question="Which deploy target should I use?",
                                       category="purchase", intent_type="preference",
                                       context={"env": "staging"}))
    assert r["decision"] == "answer" and r["answer"]["value"] == "staging"
    # Out of scope still defers.
    r2 = svc.ask(agent, QuestionRequest(request_id="q3", question="Which deploy target should I use?",
                                        category="purchase", intent_type="preference",
                                        context={"env": "production"}))
    assert r2["decision"] == "defer"


def test_answer_same_keywords_supersedes_rule():
    svc, agent = make()
    svc.ask(agent, QuestionRequest(request_id="s1", question="Which deploy target?", category="purchase"))
    svc.answer_inbox(svc.inbox()[0]["id"], "staging", save_rule={"keywords": ["deploy"]})
    svc.ask(agent, QuestionRequest(request_id="s2", question="Which deploy target?", category="purchase"))
    items = [i for i in svc.inbox()]
    out = svc.answer_inbox(items[0]["id"], "prod", save_rule={"keywords": ["deploy"]})
    assert out["rule"]["action"] == "superseded"
    versions = svc.rule_versions(out["rule"]["rule_id"])
    assert len(versions) == 2 and versions[1]["answer_json"]


def test_revalidate_after_correction():
    svc, agent = make()
    svc.create_rule("purchase", {"keywords": ["deploy", "target"]}, {"value": "staging"})
    svc.set_stage("purchase", "auto")
    r = svc.ask(agent, QuestionRequest(request_id="r1", question="Which deploy target?",
                                       category="purchase", intent_type="preference"))
    assert r["answer"]["value"] == "staging"
    rule = svc.store.query_one("SELECT id FROM rules WHERE category='purchase'")
    svc.supersede_rule(rule["id"], new_answer={"value": "prod"})
    # Clear the sliced hold as fresh human evidence / a manual clear would.
    svc.clear_holds("purchase")
    out = svc.revalidate_decision(r["decision_id"])
    assert out["answer"]["value"] == "prod"
