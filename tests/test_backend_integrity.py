"""Regression coverage for backend identity, matching, and transaction invariants."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from switchboard.config import Settings
from switchboard.domain import QuestionRequest
from switchboard.persistence import Store
from switchboard.service import SwitchboardError, SwitchboardService


def _make(store=None, scopes=None, cfg=None):
    service = SwitchboardService(store or Store(":memory:"), cfg=cfg)
    registration = service.register_agent("integrity-test", scopes=scopes)
    return service, service.authenticate(registration["api_key"])


def _ask(service, agent, request_id, **overrides):
    request = {
        "request_id": request_id,
        "question": "Which deployment target should I choose?",
        "category": "deploy",
        "intent_type": "preference",
        "context": {"environment": "staging"},
    }
    request.update(overrides)
    return service.ask(agent, QuestionRequest(**request))


def _seed_rule(service, intent="preference", example="Which deployment target should I choose?"):
    service.create_rule(
        "deploy",
        {"keywords": ["deployment", "target"], "example_question": example,
         "intent_type": intent},
        {"option_id": "staging", "value": "staging"},
        scope={"mandatory": {"environment": "staging"}},
    )
    service.set_stage("deploy", "auto")


def test_outcomes_and_dependencies_are_owned_by_the_calling_agent():
    service, owner = _make()
    other_registration = service.register_agent("other-agent")
    other = service.authenticate(other_registration["api_key"])
    _seed_rule(service)
    answer = _ask(service, owner, "owner-question")

    with pytest.raises(SwitchboardError) as outcome_error:
        service.report_outcome(other, answer["decision_id"], "success")
    assert outcome_error.value.code == "NOT_FOUND"

    with pytest.raises(SwitchboardError) as dependency_error:
        service.record_use(other, answer["receipt_id"], "task", "other-task", "used_answer")
    assert dependency_error.value.code == "NOT_FOUND"

    accepted = service.report_outcome(owner, answer["decision_id"], "success")
    assert accepted["eligible_for_calibration"] is False


def test_feedback_and_dependency_scopes_are_enforced():
    service, agent = _make(scopes=["ask"])
    _seed_rule(service)
    answer = _ask(service, agent, "restricted-scope")

    with pytest.raises(SwitchboardError) as outcome_error:
        service.report_outcome(agent, answer["decision_id"], "success")
    assert outcome_error.value.code == "FORBIDDEN_SCOPE"

    with pytest.raises(SwitchboardError) as dependency_error:
        service.record_use(agent, answer["receipt_id"], "task", "task-1", "used_answer")
    assert dependency_error.value.code == "FORBIDDEN_SCOPE"


def test_outcome_and_dependency_payloads_fail_closed_on_invalid_values():
    service, agent = _make()
    _seed_rule(service)
    answer = _ask(service, agent, "invalid-outcome-payload")

    with pytest.raises(SwitchboardError) as outcome_error:
        service.report_outcome(agent, answer["decision_id"], {"success": True})
    assert outcome_error.value.code == "INVALID_SCHEMA"

    with pytest.raises(SwitchboardError) as dependency_error:
        service.record_use(agent, answer["receipt_id"], "task", "   ", "used_answer")
    assert dependency_error.value.code == "INVALID_SCHEMA"


def test_parent_receipt_ids_reject_surrounding_whitespace():
    service, agent = _make()
    _seed_rule(service)
    parent = _ask(service, agent, "parent-for-whitespace")

    with pytest.raises(SwitchboardError) as error:
        _ask(service, agent, "child-with-whitespace", parent_receipts=[f' {parent["receipt_id"]} '])
    assert error.value.code == "INVALID_SCHEMA"


def test_agent_cannot_attach_a_dependency_to_a_deferred_receipt():
    service, agent = _make()
    result = _ask(service, agent, "deferred-receipt")

    with pytest.raises(SwitchboardError) as error:
        service.record_use(agent, result["receipt_id"], "task", "task-1", "used_answer")
    assert error.value.code == "INVALID_SCHEMA"


def test_parent_receipts_are_persisted_as_owned_dependency_edges():
    service, agent = _make()
    _seed_rule(service)
    parent = _ask(service, agent, "parent-receipt")

    child = _ask(service, agent, "child-request", parent_receipts=[parent["receipt_id"]])

    stored_question = service.store.query_one(
        "SELECT parent_receipts_json FROM questions WHERE id=?", (child["question_id"],))
    edge = service.store.query_one(
        "SELECT * FROM decision_dependencies WHERE source_receipt_id=? AND dependent_id=?",
        (parent["receipt_id"], child["decision_id"]))
    assert stored_question["parent_receipts_json"] == f'["{parent["receipt_id"]}"]'
    assert edge and edge["status"] == "pending" and edge["dependent_type"] == "decision"


def test_parent_receipts_cannot_be_attached_cross_agent():
    service, owner = _make()
    other = service.authenticate(service.register_agent("second-agent")["api_key"])
    _seed_rule(service)
    answer = _ask(service, owner, "private-parent")

    with pytest.raises(SwitchboardError) as error:
        _ask(service, other, "cross-agent-parent", parent_receipts=[answer["receipt_id"]])
    assert error.value.code == "NOT_FOUND"


def test_record_use_updates_the_existing_dependency_edge():
    service, agent = _make()
    _seed_rule(service)
    answer = _ask(service, agent, "dependency-lifecycle")
    first = service.record_use(agent, answer["receipt_id"], "task", "task-1", "used_answer", "pending")
    second = service.record_use(agent, answer["receipt_id"], "task", "task-1", "used_answer", "completed")
    rows = service.store.query(
        "SELECT id,status FROM decision_dependencies WHERE source_receipt_id=? AND dependent_id='task-1'",
        (answer["receipt_id"],))

    assert first["dependency_id"] == second["dependency_id"]
    assert rows == [{"id": first["dependency_id"], "status": "completed"}]


def test_batch_answer_records_a_decision_and_receipt_for_each_question():
    service, agent = _make()
    base = {"question": "Can I restart the staging service?", "category": "infra",
            "intent_type": "action_review", "reversibility": "reversible",
            "context": {"project": "alpha"},
            "options": [{"id": "allow", "label": "Allow", "value": True},
                        {"id": "deny", "label": "Deny", "value": False}]}
    first = service.ask(agent, QuestionRequest(request_id="batch-1", **base))
    second = service.ask(agent, QuestionRequest(request_id="batch-2", **base))
    items = service.inbox()
    assert len(items) == 2 and items[0]["batch_id"] == items[1]["batch_id"]

    result = service.answer_inbox(items[0]["id"], {"option_id": "allow", "value": True})

    assert result["batch_propagated"] is True
    assert set(result["propagated_question_ids"]) == {first["question_id"], second["question_id"]} - {
        items[0]["question_id"]}
    for question_id in (first["question_id"], second["question_id"]):
        status = service.action_request_status(agent, question_id)
        assert status["status"] == "answered"
        assert status["answer"]["option_id"] == "allow"
    assert service.inbox() == []
    batch = service.store.query_one("SELECT status FROM attention_batches WHERE id=?", (items[0]["batch_id"],))
    assert batch["status"] == "resolved"


def test_attention_does_not_batch_different_contexts():
    service, agent = _make()
    common = {"question": "Can I restart the staging service?", "category": "infra",
              "intent_type": "action_review", "reversibility": "reversible",
              "options": [{"id": "allow", "label": "Allow"}, {"id": "deny", "label": "Deny"}]}
    service.ask(agent, QuestionRequest(request_id="context-a", context={"project": "alpha"}, **common))
    service.ask(agent, QuestionRequest(request_id="context-b", context={"project": "beta"}, **common))

    items = service.inbox()
    assert len(items) == 2
    assert items[0]["batch_id"] != items[1]["batch_id"]


def test_attention_priority_uses_deadline_slack_and_locked_override():
    now = datetime.now(timezone.utc)
    common = {"request_id": "priority", "question": "Question", "category": "misc"}
    base = QuestionRequest(**common)
    soon = QuestionRequest(**{**common, "deadline_at": (now + timedelta(minutes=20)).isoformat()})
    later = QuestionRequest(**{**common, "deadline_at": (now + timedelta(days=20)).isoformat()})

    normal = SwitchboardService._attention_priority(base, {"risk_class": "standard"})
    near_deadline = SwitchboardService._attention_priority(soon, {"risk_class": "standard"})
    far_deadline = SwitchboardService._attention_priority(later, {"risk_class": "standard"})
    locked = SwitchboardService._attention_priority(base, {"risk_class": "locked"})

    assert near_deadline[0] > far_deadline[0] > normal[0]
    assert locked == (100.0, "critical")


def test_blast_radius_distinguishes_changed_and_unchanged_rule_effects():
    service, agent = _make()
    _seed_rule(service)
    answer = _ask(service, agent, "impact-status")
    service.record_use(agent, answer["receipt_id"], "task", "pending-task", "used_answer", "pending")
    service.record_use(agent, answer["receipt_id"], "task", "failed-task", "used_answer", "failed")
    service.record_use(agent, answer["receipt_id"], "task", "unknown-task", "used_answer", "unknown")
    rule = service.store.query_one("SELECT id FROM rules WHERE category='deploy'")

    unchanged = service.supersede_rule(
        rule["id"], new_answer={"option_id": "staging", "value": "staging"})["blast_radius"]
    unchanged_by_id = {item["dependent_id"]: item for item in unchanged["affected"]}
    assert unchanged_by_id["pending-task"]["proposed_status"] == "unaffected"

    changed = service.supersede_rule(
        rule["id"], new_answer={"option_id": "production", "value": "production"})["blast_radius"]
    changed_by_id = {item["dependent_id"]: item for item in changed["affected"]}
    assert changed_by_id["pending-task"]["proposed_status"] == "revalidate"
    assert changed_by_id["failed-task"]["proposed_status"] == "review_failed"
    assert changed_by_id["unknown-task"]["proposed_status"] == "unknown_dependency_coverage"


def test_semantic_matching_respects_intent_predicates():
    service, agent = _make()
    _seed_rule(service, intent="preference")

    result = _ask(service, agent, "intent-mismatch", intent_type="permission")

    assert result["decision"] == "defer"
    assert result["answer"] is None
    assert result["reason_code"] == "below_policy"


def test_enforced_risk_gate_defers_until_evidence_is_sufficient():
    service, agent = _make(cfg=Settings(risk_gate_mode="enforce"))
    _seed_rule(service)

    result = _ask(service, agent, "risk-gate-enforce")

    assert result["decision"] == "defer"
    assert result["reason_code"] == "risk_gate_insufficient_evidence"
    assert result["risk_gate"]["mode"] == "enforce"
    assert result["risk_gate"]["blocked"] is True


def test_equal_semantic_candidates_defer_instead_of_choosing_arbitrarily():
    service, agent = _make()
    predicate = {"keywords": ["never-match-t0"],
                 "example_question": "Which deployment target should I choose?",
                 "intent_type": "preference"}
    service.create_rule("deploy", predicate, {"value": "staging"},
                        scope={"mandatory": {"environment": "staging"}})
    service.create_rule("deploy", predicate, {"value": "production"},
                        scope={"mandatory": {"environment": "staging"}})
    service.set_stage("deploy", "auto")

    result = _ask(service, agent, "ambiguous-match")

    assert result["decision"] == "defer"
    assert result["reason_code"] == "ambiguous_match"
    assert result["matcher_tier"] == "T1"


def test_transaction_rolls_back_all_mutations_and_cache_generation():
    store = Store(":memory:")
    generation = store.write_seq

    with pytest.raises(RuntimeError):
        with store.transaction():
            store.emit("test", "one", "first", "thing", "one")
            store.emit("test", "one", "second", "thing", "two")
            raise RuntimeError("fail after writes")

    assert store.query_one("SELECT COUNT(*) AS n FROM events")["n"] == 0
    assert store.write_seq == generation


def test_nested_savepoint_rollback_preserves_outer_transaction():
    store = Store(":memory:")
    generation = store.write_seq

    with store.transaction():
        store.emit("test", "one", "outer.before", "thing", "one")
        with pytest.raises(ValueError):
            with store.transaction():
                store.emit("test", "one", "inner.rolled_back", "thing", "two")
                raise ValueError("rollback nested unit")
        store.emit("test", "one", "outer.after", "thing", "three")

    kinds = [r["event_type"] for r in store.query("SELECT event_type FROM events ORDER BY rowid")]
    assert kinds == ["outer.before", "outer.after"]
    assert store.write_seq == generation + 1


def test_action_review_cannot_be_reapproved_or_consumed_twice():
    service, agent = _make()
    action = {"type": "sandbox_deploy", "target": "staging"}
    review = service.request_action_review(agent, action)
    service.approve_action(review["review_id"])

    assert service.verify_action_execution(review["review_id"], action)["executed"] is True
    with pytest.raises(SwitchboardError) as approval_error:
        service.approve_action(review["review_id"])
    assert approval_error.value.code == "CONFLICT"
    with pytest.raises(SwitchboardError) as execution_error:
        service.verify_action_execution(review["review_id"], action)
    assert execution_error.value.code == "LOCKED_ACTION"


def test_expired_action_review_cannot_be_approved():
    service, agent = _make()
    review = service.request_action_review(agent, {"type": "sandbox_deploy"},
                                           expires_at="2000-01-01T00:00:00+00:00")

    with pytest.raises(SwitchboardError) as error:
        service.approve_action(review["review_id"])
    assert error.value.code == "GRANT_EXPIRED"


def test_concurrent_idempotent_asks_return_the_same_committed_decision(tmp_path):
    db = str(tmp_path / "concurrent-ask.db")
    service_a, owner = _make(Store(db))
    _seed_rule(service_a)
    service_b = SwitchboardService(Store(db))
    # Both services share the database and the authenticated principal.
    owner_b = {**owner, "scopes_json": owner["scopes_json"]}

    def perform(service, principal):
        return _ask(service, principal, "same-request")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(perform, service_a, owner), pool.submit(perform, service_b, owner_b)]
        results = [future.result(timeout=10) for future in futures]

    assert results[0]["decision_id"] == results[1]["decision_id"]
    assert service_a.store.query_one(
        "SELECT COUNT(*) AS n FROM questions WHERE agent_id=? AND request_id=?",
        (owner["id"], "same-request"))["n"] == 1
