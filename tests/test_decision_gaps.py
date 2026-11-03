"""Behavioral regressions for the end-to-end backend review findings."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

from switchboard.config import Settings
from switchboard.domain import QuestionRequest
from switchboard.persistence import Store
from switchboard.service import SwitchboardError, SwitchboardService


def make(store=None, scopes=None):
    service = SwitchboardService(store or Store(":memory:"), cfg=Settings(enable_t3=False))
    agent = service.authenticate(service.register_agent("gap-test", scopes=scopes)["api_key"])
    return service, agent


def seed(service, predicate=None):
    rule = service.create_rule(
        "deploy", predicate if predicate is not None else {"keywords": ["deployment", "target"]},
        {"value": "staging"}, scope={"mandatory": {"environment": "staging"}})
    service.set_stage("deploy", "auto")
    return rule


def ask(service, agent, request_id, **overrides):
    args = {"request_id": request_id, "question": "Which deployment target?", "category": "deploy",
            "intent_type": "preference", "reversibility": "reversible",
            "context": {"environment": "staging"}}
    args.update(overrides)
    return service.ask(agent, QuestionRequest(**args))


def answer(service, result, value):
    item = next(item for item in service.inbox() if item["question_id"] == result["question_id"])
    return service.answer_inbox(item["id"], {"value": value})


@pytest.mark.parametrize("risk", [
    {"action": {"type": "delete", "target": "staging"}},
    {"risk_hint": "locked"},
    {"context": {"environment": "staging", "money_movement": True}},
    {"intent_type": "action_review", "reversibility": "unknown"},
])
def test_revalidation_retains_risk_and_parent_receipts(risk):
    service, agent = make()
    seed(service)
    parent = ask(service, agent, "parent")
    original = ask(service, agent, "locked", parent_receipts=[parent["receipt_id"]], **risk)
    assert original["reason_code"] == "locked"

    result = service.revalidate_decision(original["decision_id"])

    assert result["decision"] == "defer" and result["reason_code"] == "locked"
    stored = service.store.query_one("SELECT * FROM questions WHERE id=?", (result["question_id"],))
    assert json.loads(stored["action_json"] or "null") == risk.get("action")
    assert json.loads(stored["parent_receipts_json"]) == [parent["receipt_id"]]


def test_legacy_question_migration_keeps_unrecoverable_action_locked(tmp_path):
    path = str(tmp_path / "legacy.db")
    service, agent = make(Store(path))
    seed(service)
    original = ask(service, agent, "legacy-delete", action={"type": "delete"})
    service.store.close()
    # Reproduce a ledger made before actions were persisted.
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE questions DROP COLUMN action_json")
    reopened = SwitchboardService(Store(path), cfg=Settings(enable_t3=False))

    result = reopened.revalidate_decision(original["decision_id"])

    assert result["decision"] == "defer" and result["reason_code"] == "locked"
    reopened.store.close()


def test_revalidation_honors_owner_and_disabled_agent():
    service, agent = make()
    seed(service)
    result = ask(service, agent, "owner")
    other = service.authenticate(service.register_agent("other")["api_key"])
    with pytest.raises(SwitchboardError, match="decision"):
        service.revalidate_decision(result["decision_id"], agent=other)
    service.store.execute("UPDATE agents SET enabled=0 WHERE id=?", (agent["id"],))
    with pytest.raises(SwitchboardError) as error:
        service.revalidate_decision(result["decision_id"])
    assert error.value.code == "UNAUTHENTICATED"


@pytest.mark.parametrize("predicate", [
    {}, {"category": "deploy"}, {"keywords": ["", "  "]},
    {"example_question": "Which deployment target?"},
])
def test_rules_without_exact_predicates_do_not_answer_unrelated_questions(predicate):
    service, agent = make()
    seed(service, predicate)
    result = ask(service, agent, "unrelated", question="Choose a color for logs")
    assert result["decision"] == "defer" and result["answer"] is None


def test_example_only_rule_uses_semantic_tier_for_relevant_questions():
    service, agent = make()
    seed(service, {"example_question": "Which deployment target?"})
    result = ask(service, agent, "relevant")
    assert result["decision"] == "answer" and result["matcher_tier"] == "T1"


@pytest.mark.parametrize("changes,value", [
    ({"question": "Choose a color for logs"}, "blue"),
    ({"context": {"environment": "production"}}, "canary"),
    ({}, "production"),
])
def test_unrelated_out_of_scope_or_disagreeing_answers_cannot_release_hold(changes, value):
    service, agent = make()
    rule = seed(service)
    service.supersede_rule(rule["rule_id"], new_answer={"value": "canary"})
    result = ask(service, agent, "not-a-confirmation", **changes)
    answer(service, result, value)
    hold = service.list_holds("deploy")[0]
    assert hold["status"] == "held" and hold["fresh_count"] == 0


def test_another_rule_in_same_scope_cannot_release_hold():
    service, agent = make()
    rule = seed(service)
    service.create_rule("deploy", {"keywords": ["log", "color"]}, {"value": "blue"},
                        scope={"mandatory": {"environment": "staging"}})
    service.supersede_rule(rule["rule_id"], new_answer={"value": "canary"})
    other = ask(service, agent, "other-rule", question="Which log color?")
    service.confirm_feedback(other["decision_id"], "correct")
    assert service.list_holds("deploy")[0]["fresh_count"] == 0


def test_negative_feedback_does_not_release_hold_but_current_positive_does():
    service, agent = make()
    rule = seed(service)
    old = ask(service, agent, "before-correction")
    service.supersede_rule(rule["rule_id"], new_answer={"value": "canary"})
    current = ask(service, agent, "after-correction")
    service.confirm_feedback(old["decision_id"], "correct")
    service.confirm_feedback(current["decision_id"], "incorrect")
    assert service.list_holds("deploy")[0]["status"] == "held"
    confirmed = ask(service, agent, "fresh-check")
    answer(service, confirmed, "canary")
    assert service.list_holds("deploy")[0]["status"] == "released"


def test_repeated_corrections_replace_old_holds_and_only_current_version_can_release():
    service, agent = make()
    rule = seed(service)
    service.supersede_rule(rule["rule_id"], new_answer={"value": "canary"})
    stale = ask(service, agent, "old-held-version")
    service.supersede_rule(rule["rule_id"], new_answer={"value": "preview"})
    answer(service, stale, "canary")
    assert rule["rule_id"] in service.held_rule_ids("deploy")
    current = ask(service, agent, "new-held-version")
    answer(service, current, "preview")
    assert rule["rule_id"] not in service.held_rule_ids("deploy")
    assert ask(service, agent, "resumed")["answer"] == {"value": "preview"}


def test_startup_retires_legacy_holds_for_superseded_versions(tmp_path):
    path = str(tmp_path / "legacy-holds.db")
    service, agent = make(Store(path))
    rule = seed(service)
    service.supersede_rule(rule["rule_id"], new_answer={"value": "canary"})
    service.supersede_rule(rule["rule_id"], new_answer={"value": "preview"})
    service.store.execute("UPDATE recalibration_holds SET status='held'")
    service.store.close()
    reopened = SwitchboardService(Store(path), cfg=Settings(enable_t3=False))
    assert len([hold for hold in reopened.list_holds("deploy") if hold["status"] == "held"]) == 1
    current = ask(reopened, agent, "current-version")
    answer(reopened, current, "preview")
    assert reopened.held_rule_ids("deploy") == set()
    reopened.store.close()


def test_automatic_answers_leave_inbox_and_close_batch_without_hiding_deferred_work():
    service, agent = make()
    seed(service)
    options = [{"id": "staging", "label": "Staging"}, {"id": "preview", "label": "Preview"}]
    service.set_stage("deploy", "suggest")
    waiting = ask(service, agent, "waiting", options=options)
    service.set_stage("deploy", "auto")
    automatic = ask(service, agent, "automatic", options=options)
    assert [item["question_id"] for item in service.inbox()] == [waiting["question_id"]]
    item = service.store.query_one("SELECT * FROM attention_items WHERE question_id=?",
                                   (automatic["question_id"],))
    assert item["status"] == "resolved"
    batch = service.store.query_one("SELECT status FROM attention_batches WHERE id=?", (item["batch_id"],))
    assert batch["status"] == "open"
    answer(service, waiting, "staging")
    # A later automatic question gets a new, immediately closed batch.
    later = ask(service, agent, "later", options=options)
    later_item = service.store.query_one("SELECT * FROM attention_items WHERE question_id=?", (later["question_id"],))
    assert later_item["batch_id"] != item["batch_id"]
    assert service.store.query_one("SELECT status FROM attention_batches WHERE id=?",
                                   (later_item["batch_id"],))["status"] == "resolved"
    assert service.inbox() == [] and service.notices() == []


def test_startup_reconciles_legacy_auto_and_warn_attention(tmp_path):
    path = str(tmp_path / "attention.db")
    service, agent = make(Store(path))
    seed(service)
    automatic = ask(service, agent, "automatic")
    service.set_stage("deploy", "warn")
    warned = ask(service, agent, "warned")
    service.store.execute("UPDATE attention_items SET status='queued'")
    service.store.close()
    reopened = SwitchboardService(Store(path), cfg=Settings(enable_t3=False))
    assert reopened.inbox() == []
    assert [item["question_id"] for item in reopened.notices()] == [warned["question_id"]]
    assert reopened.store.query_one("SELECT status FROM attention_items WHERE question_id=?",
                                   (automatic["question_id"],))["status"] == "resolved"
    reopened.store.close()


@pytest.mark.parametrize("stage,mode", [("shadow", "shadow"), ("suggest", "auto"),
                                        ("warn", "warn"), ("auto", "auto")])
def test_away_only_upgrades_suggest(stage, mode):
    service, agent = make()
    seed(service)
    service.set_stage("deploy", stage)
    service.create_away_grant(["deploy"], ["preference"],
                             (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    result = ask(service, agent, "away")
    stored = service.store.query_one("SELECT mode FROM decisions WHERE id=?", (result["decision_id"],))
    assert stored["mode"] == mode
    assert result["requires_human"] == (mode == "shadow")


@pytest.mark.parametrize("scopes", [[], ["get_rules"], ["record_use", "report_outcome"]])
def test_missing_ask_scope_is_rejected_before_writing_any_question(scopes):
    service, agent = make(scopes=scopes)
    assert json.loads(agent["scopes_json"]) == scopes
    with pytest.raises(SwitchboardError) as error:
        ask(service, agent, "forbidden")
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert service.store.query_one("SELECT COUNT(*) n FROM questions")["n"] == 0


def test_scope_revocation_blocks_revalidation_and_answer_polling():
    service, agent = make()
    result = ask(service, agent, "before-revocation")
    service.store.execute("UPDATE agents SET scopes_json='[]' WHERE id=?", (agent["id"],))
    restricted = service.authenticate_agent_id(agent["id"])
    for operation in (
        lambda: service.revalidate_decision(result["decision_id"]),
        lambda: service.action_request_status(restricted, result["question_id"], expected_intent=None),
    ):
        with pytest.raises(SwitchboardError) as error:
            operation()
        assert error.value.code == "FORBIDDEN_SCOPE"


def test_different_actions_cannot_share_an_attention_batch():
    service, agent = make()
    options = [{"id": "allow", "label": "Allow"}, {"id": "deny", "label": "Deny"}]
    one = ask(service, agent, "first-action", intent_type="action_review", options=options,
              action={"type": "restart", "target": "service-a"})
    two = ask(service, agent, "second-action", intent_type="action_review", options=options,
              action={"type": "restart", "target": "service-b"})
    answer(service, one, "allow")
    assert service.action_request_status(agent, two["question_id"])["status"] == "pending"


@pytest.fixture()
def claude_gate():
    path = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "switchboard_gate.py"
    spec = importlib.util.spec_from_file_location("claude_gap_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_claude_question_hook_polls_the_general_answer_route(claude_gate, monkeypatch):
    service, agent = make()
    emitted, paths = [], []

    def api(_url, _key, path, body=None):
        paths.append(path)
        if path == "/api/ask":
            return service.ask(agent, QuestionRequest(**body))
        prefix, question_id, suffix = path.rsplit("/", 2)
        assert prefix == "/api/questions" and suffix == "answer"
        item = next(i for i in service.inbox() if i["question_id"] == question_id)
        service.answer_inbox(item["id"], {"option_id": "option_2"})
        return service.action_request_status(agent, question_id, expected_intent=None)

    monkeypatch.setattr(claude_gate, "call_api", api)
    monkeypatch.setattr(claude_gate, "record_use", lambda *args: None)
    monkeypatch.setattr(claude_gate, "save_approval", lambda *args: None)
    monkeypatch.setattr(claude_gate, "emit", lambda *args: emitted.append(args))
    claude_gate.answer_user_question({
        "session_id": "session", "tool_use_id": "question",
        "tool_input": {"questions": [{"question": "Choose a color", "options": [
            {"label": "Blue"}, {"label": "Green"}]}]},
    }, "https://example.test", "unused")
    assert paths[-1].endswith("/answer")
    assert emitted[0][0] == "allow"
    assert emitted[0][2]["answers"] == {"Choose a color": "Green"}


def test_claude_action_polling_retains_its_existing_route(claude_gate, monkeypatch):
    paths = []
    def api(_url, _key, path):
        paths.append(path)
        return {"status": "answered", "answer": {"option_id": "deny"}}
    monkeypatch.setattr(claude_gate, "call_api", api)
    result = claude_gate.human_answer("https://example.test", "unused", "action/123")
    assert paths == ["/api/action-requests/action%2F123"]
    assert result["answer"]["option_id"] == "deny"
