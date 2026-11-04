import pytest

from switchboard.benchmark import isolated_service
from switchboard.domain import QuestionRequest
from switchboard.matching import MatcherLadder
from switchboard.persistence import Store
from switchboard.service import SwitchboardError, SwitchboardService


@pytest.fixture
def setup():
    svc = isolated_service()
    reg = svc.register_agent("policy-fixture", "test")
    try:
        yield svc, svc.authenticate(reg["api_key"])
    finally:
        svc.store.close()


def rule(svc, value="markdown", scope=None, predicate=None, category="reports"):
    return svc.create_rule(category, predicate or {"keywords": ["report", "format"], "intent_type": "preference"},
                           {"value": value}, scope={"mandatory": {"project": "atlas"}} if scope is None else scope)


def ask(svc, agent, id, context=None, **extra):
    svc.set_stage("reports", "auto")
    return svc.ask(agent, QuestionRequest(request_id=id, question="Which report format?", category="reports",
                                          intent_type="preference", context=context or {"project": "atlas"},
                                          **extra))


def confirm(svc, response, value):
    item = next(i for i in svc.inbox() if i["question_id"] == response["question_id"])
    return svc.answer_inbox(item["id"], {"value": value}, actor="synthetic_oracle")


def test_contract_blocks_preexisting_incomplete_rule_and_explains_it(setup):
    svc, agent = setup
    made = rule(svc, scope={"mandatory": {"workspace": "drafts"}})
    out = svc.set_scope_contract("reports", ["project", "workspace"])
    assert out["existing_rule_violations"][0]["rule_id"] == made["rule_id"]
    assert out["existing_rule_violations"][0]["missing_fields"] == ["project"]
    result = ask(svc, agent, "legacy", {"workspace": "drafts", "project": "boreal"})
    assert result["decision"] == "defer" and result["reason_code"] == "scope_contract_incomplete"
    assert result["match_diagnostics"]["rule_scope"]["missing_fields"] == ["project"]


def test_contract_applies_to_create_and_correction_atomically(setup):
    svc, _ = setup
    svc.set_scope_contract("reports", ["project"])
    with pytest.raises(SwitchboardError, match="project"):
        rule(svc, scope={"mandatory": {"workspace": "drafts"}})
    assert svc.list_rules_human() == []
    made = rule(svc)
    with pytest.raises(SwitchboardError):
        svc.supersede_rule(made["rule_id"], new_scope={"mandatory": {"workspace": "drafts"}})
    assert len(svc.rule_versions(made["rule_id"])) == 1
    assert svc.list_holds() == []


def test_global_scope_requires_category_permission_and_explicit_rule(setup):
    svc, agent = setup
    svc.set_scope_contract("reports", ["project"])
    with pytest.raises(SwitchboardError) as error:
        rule(svc, scope={"global": True})
    assert error.value.code == "GLOBAL_RULE_NOT_ALLOWED"
    svc.set_scope_contract("reports", ["project"], allow_global=True)
    with pytest.raises(SwitchboardError):
        rule(svc, scope={})
    rule(svc, scope={"global": True})
    assert ask(svc, agent, "global", {"project": "boreal"})["decision"] == "answer"
    assert ask(svc, agent, "locked", {"project": "boreal", "money_movement": True})["reason_code"] == "locked"


def test_unconfigured_categories_are_legacy_compatible_and_isolated(setup):
    svc, agent = setup
    svc.set_scope_contract("coding", ["repo"])
    assert not svc.scope_contract("reports")["configured"]
    rule(svc, scope={})
    assert ask(svc, agent, "legacy-compatible")["decision"] == "answer"


@pytest.mark.parametrize("scope", [[], {"mandatory": []}, {"mandatory": {"project": []}},
                                   {"mandatory": {"project": None}}, {"mandatory": {"project": {"id": "a"}}},
                                   {"mandatory": {"project": " "}}, {"mandatory": {"": "atlas"}},
                                   {"global": "true"}, {"global": True, "mandatory": {"project": "a"}},
                                   {"mandatory": {"amount": float("nan")}}, {"mandatroy": {"project": "a"}}])
def test_malformed_scope_never_becomes_an_unbounded_rule(setup, scope):
    svc, _ = setup
    with pytest.raises(SwitchboardError):
        rule(svc, scope=scope)
    assert not svc.list_rules_human()


@pytest.mark.parametrize("fields", ["project", [""], [" project"], [None], ["a"] * 33])
def test_contract_schema_rejects_ambiguous_field_definitions(setup, fields):
    svc, _ = setup
    with pytest.raises(SwitchboardError):
        svc.set_scope_contract("reports", fields)
    assert not svc.scope_contract("reports")["configured"]


@pytest.mark.parametrize("reverse", [False, True])
def test_equal_exact_conflicts_defer_regardless_of_insertion_order(setup, reverse):
    svc, agent = setup
    made = [rule(svc, value=v) for v in (("pdf", "markdown") if reverse else ("markdown", "pdf"))]
    out = ask(svc, agent, "conflict")
    assert out["decision"] == "defer" and out["reason_code"] == "conflicting_rules"
    assert set(out["match_diagnostics"]["conflicting_rule_version_ids"]) == {r["version_id"] for r in made}


@pytest.mark.parametrize("reverse", [False, True])
def test_specific_scope_overrides_general_default_in_either_order(setup, reverse):
    svc, agent = setup
    choices = [("markdown", {}), ("pdf", {"mandatory": {"project": "atlas"}})]
    for value, scope in reversed(choices) if reverse else choices:
        rule(svc, value=value, scope=scope)
    assert ask(svc, agent, "atlas")["answer"]["value"] == "pdf"
    assert ask(svc, agent, "boreal", {"project": "boreal"})["answer"]["value"] == "markdown"
    assert ask(svc, agent, "unknown-project", {"nonce": "one"})["decision"] == "defer"


def test_incomparable_boundaries_do_not_use_number_of_fields_as_precedence(setup):
    svc, agent = setup
    rule(svc, scope={"mandatory": {"project": "atlas"}})
    rule(svc, value="pdf", scope={"mandatory": {"team": "core", "workspace": "drafts"}})
    result = ask(svc, agent, "incomparable", {"project": "atlas", "team": "core", "workspace": "drafts"})
    assert result["reason_code"] == "conflicting_rules"


def test_missing_scope_cannot_hide_a_potential_incomparable_conflict(setup):
    svc, agent = setup
    rule(svc, predicate={"keywords": ["report"]})
    rule(svc, value="pdf", scope={"mandatory": {"team": "core"}}, predicate={"keywords": ["format"]})
    # Supplying the team would reveal a conflict; omitting it cannot authorize the first rule.
    assert ask(svc, agent, "missing-team")["decision"] == "defer"
    assert ask(svc, agent, "both", {"project": "atlas", "team": "core"})["reason_code"] == "conflicting_rules"


def test_list_scope_containment_and_same_answer_duplicates(setup):
    svc, agent = setup
    rule(svc, scope={"mandatory": {"project": ["atlas", "boreal"]}})
    specific = rule(svc, value="pdf")
    duplicate = rule(svc, value="pdf")
    out = ask(svc, agent, "list-scope")
    assert out["answer"]["value"] == "pdf"
    assert out["rule_versions"] == [min(specific["version_id"], duplicate["version_id"])]


def test_explicit_exact_question_is_not_ignored_when_keywords_exist(setup):
    svc, agent = setup
    rule(svc, predicate={"keywords": ["report"], "exact_question": "Which report format?"})
    result = svc.ask(agent, QuestionRequest(request_id="different", question="Delete this report?",
                                           category="reports", context={"project": "atlas"}, intent_type="preference"))
    # No example means there is no semantic fallback to bypass the exact question.
    assert result["decision"] == "defer"


def test_boolean_and_number_scope_values_are_not_interchangeable(setup):
    svc, agent = setup
    rule(svc, scope={"mandatory": {"flag": True}})
    assert ask(svc, agent, "number", {"flag": 1})["decision"] == "defer"
    assert ask(svc, agent, "boolean", {"flag": True})["decision"] == "answer"


def test_identical_correction_preserves_version_epoch_and_existing_hold(setup):
    svc, agent = setup
    made = rule(svc)
    epoch = svc.category("reports")["active_preference_epoch"]
    no_op = svc.supersede_rule(made["rule_id"], new_answer={"value": "markdown"},
                               new_predicate={"keywords": ["FORMAT", " report "], "intent_type": "preference"})
    assert not no_op["changed"] and no_op["version_id"] == made["version_id"]
    assert svc.category("reports")["active_preference_epoch"] == epoch
    assert not svc.list_holds()
    changed = svc.supersede_rule(made["rule_id"], new_answer={"value": "pdf"})
    pending = ask(svc, agent, "held")
    hold_before = svc.list_holds()
    again = svc.supersede_rule(made["rule_id"], new_answer={"value": "pdf"})
    assert again["version_id"] == changed["version_id"] and again["preserves_hold"]
    assert svc.list_holds() == hold_before
    confirm(svc, pending, "pdf")
    assert ask(svc, agent, "released")["decision"] == "answer"


def test_narrowing_preserves_automation_but_cannot_escape_a_hold(setup):
    svc, agent = setup
    made = rule(svc, scope={"mandatory": {"project": ["atlas", "boreal"]}})
    narrowed = svc.supersede_rule(made["rule_id"], new_scope={"mandatory": {"project": "atlas"}})
    assert narrowed["change_kind"] == "scope_narrowed" and narrowed["required_confirmations"] == 0
    assert ask(svc, agent, "narrow")["decision"] == "answer"
    assert ask(svc, agent, "outside", {"project": "boreal"})["decision"] == "defer"
    svc.supersede_rule(made["rule_id"], new_answer={"value": "pdf"})
    still_held = svc.supersede_rule(made["rule_id"], new_scope={"mandatory": {"project": "atlas", "team": "core"}})
    assert still_held["required_confirmations"] >= 1
    assert ask(svc, agent, "still-held", {"project": "atlas", "team": "core"})["decision"] == "defer"


def test_scope_widening_requires_three_meaningfully_distinct_confirmations(setup):
    svc, agent = setup
    made = rule(svc)
    update = svc.supersede_rule(made["rule_id"], new_scope={"mandatory": {"project": ["atlas", "boreal", "cirrus"]}})
    assert update["required_confirmations"] == 3
    for index in range(3):
        out = ask(svc, agent, f"metadata-{index}", {"project": "atlas", "task": str(index), "timestamp": index})
        confirm(svc, out, "markdown")
    assert svc.list_holds()[0]["fresh_count"] == 1
    for project in ("boreal", "cirrus"):
        confirm(svc, ask(svc, agent, project, {"project": project}), "markdown")
    assert ask(svc, agent, "resumed")["decision"] == "answer"


def test_contract_controls_extra_evidence_dimensions_and_resets_old_basis(setup):
    svc, agent = setup
    svc.set_scope_contract("reports", ["project"], evidence_fields=["document_kind"])
    made = rule(svc, predicate={"example_question": "Which report format?", "intent_type": "preference"})
    svc.supersede_rule(made["rule_id"], new_answer={"value": "pdf"})
    for index in range(3):
        confirm(svc, ask(svc, agent, f"teams-{index}", {"project": "atlas", "team": str(index)}), "pdf")
    assert svc.list_holds()[0]["fresh_count"] == 1
    svc.set_scope_contract("reports", ["project"], evidence_fields=["document_kind", "region"])
    assert svc.list_holds()[0]["fresh_count"] == 0
    for kind in ("memo", "analysis", "summary"):
        confirm(svc, ask(svc, agent, kind, {"project": "atlas", "document_kind": kind}), "pdf")
    assert ask(svc, agent, "done")["decision"] == "answer"


def test_old_full_context_hashes_cannot_supply_new_distinct_evidence(setup):
    svc, agent = setup
    made = rule(svc, predicate={"example_question": "Which report format?"})
    svc.supersede_rule(made["rule_id"], new_answer={"value": "pdf"})
    svc.store.execute("UPDATE recalibration_holds SET fresh_count=2, seen_contexts_json=?", ('["old-a", "old-b"]',))
    confirm(svc, ask(svc, agent, "fresh"), "pdf")
    assert svc.list_holds()[0]["fresh_count"] == 1
    assert svc.list_holds()[0]["status"] == "held"


def test_preview_uses_proposed_answer_and_never_mutates_ledger(setup):
    svc, agent = setup
    made = rule(svc)
    out = ask(svc, agent, "before")
    svc.record_use(agent, out["receipt_id"], "draft", "draft-one", "used_answer", "completed")
    generation = svc.store.cache_generation()
    preview = svc.preview_rule_update(made["rule_id"], new_answer={"value": "pdf"})
    assert preview["changed"] and preview["required_confirmations"] == 1
    assert preview["blast_radius"]["affected"][0]["proposed_status"] == "review_completed"
    assert svc.blast_radius(made["rule_id"])["affected"][0]["proposed_status"] == "unaffected"
    assert svc.store.cache_generation() == generation
    assert len(svc.rule_versions(made["rule_id"])) == 1 and not svc.list_holds()


def test_new_conflict_created_during_matching_cannot_slip_through(setup):
    svc, agent = setup
    rule(svc)
    class ConcurrentLadder(MatcherLadder):
        def resolve(self, *args, **kwargs):
            found = super().resolve(*args, **kwargs)
            rule(svc, value="pdf")
            return found
    svc.ladder = ConcurrentLadder()
    out = ask(svc, agent, "race")
    assert out["decision"] == "defer" and out["reason_code"] == "rules_changed_during_match"


def test_scope_contract_persists_across_connections(tmp_path):
    path = str(tmp_path / "policy.db")
    first = SwitchboardService(Store(path))
    try:
        first.set_scope_contract("reports", ["project"], evidence_fields=["document_kind"])
        second = SwitchboardService(Store(path))
        try:
            assert second.scope_contract("reports") == first.scope_contract("reports")
        finally:
            second.store.close()
    finally:
        first.store.close()


def test_rule_sheet_preserves_separate_project_preferences(setup):
    svc, agent = setup
    for project, value in (("atlas", "markdown"), ("boreal", "pdf")):
        out = svc.ask(agent, QuestionRequest(request_id=project, question="Which report format?", category="reports",
                                             intent_type="preference", context={"project": project}))
        item = next(i for i in svc.inbox() if i["question_id"] == out["question_id"])
        svc.answer_inbox(item["id"], {"value": value}, origin="rule_sheet",
                         save_rule={"keywords": ["report", "format"], "scope": {"mandatory": {"project": project}}})
    assert len(svc.list_rules_human()) == 2
    assert ask(svc, agent, "atlas-again")["answer"]["value"] == "markdown"
    assert ask(svc, agent, "boreal-again", {"project": "boreal"})["answer"]["value"] == "pdf"


def test_stale_preview_cannot_overwrite_a_more_recent_correction(setup):
    svc, _ = setup
    made = rule(svc)
    svc.preview_rule_update(made["rule_id"], new_answer={"value": "pdf"}, expected_version_id=made["version_id"])
    latest = svc.supersede_rule(made["rule_id"], new_answer={"value": "csv"})
    with pytest.raises(SwitchboardError) as error:
        svc.supersede_rule(made["rule_id"], new_answer={"value": "pdf"}, expected_version_id=made["version_id"])
    assert error.value.code == "CONFLICT"
    assert svc.list_rules_human()[0]["version_id"] == latest["version_id"]


def test_failed_rule_sheet_scope_validation_does_not_resolve_the_question(setup):
    svc, agent = setup
    svc.set_scope_contract("reports", ["project", "workspace"])
    result = ask(svc, agent, "unanswered")
    item = next(i for i in svc.inbox() if i["question_id"] == result["question_id"])
    with pytest.raises(SwitchboardError):
        svc.answer_inbox(item["id"], {"value": "markdown"}, origin="rule_sheet",
                         save_rule={"keywords": ["report"], "scope": {"mandatory": {"project": "atlas"}}})
    assert svc.action_request_status(agent, result["question_id"], expected_intent=None)["status"] == "pending"
    assert not svc.list_rules_human()


def test_nested_metadata_cannot_farm_distinct_contexts(setup):
    svc, agent = setup
    made = rule(svc, predicate={"example_question": "Which report format?"})
    svc.supersede_rule(made["rule_id"], new_answer={"value": "pdf"})
    for index in range(3):
        out = ask(svc, agent, f"nested-{index}", {"project": "atlas", "team": {"nonce": index}})
        confirm(svc, out, "pdf")
    assert svc.list_holds()[0]["fresh_count"] == 1
    assert svc.list_holds()[0]["status"] == "held"


def test_explicit_review_releases_only_the_selected_version_without_manufacturing_gold(setup):
    svc, agent = setup
    first = rule(svc)
    other = rule(svc, predicate={"keywords": ["chart", "units"]})
    first_new = svc.supersede_rule(first["rule_id"], new_answer={"value": "pdf"})
    svc.supersede_rule(other["rule_id"], new_answer={"value": "metric"})
    with pytest.raises(SwitchboardError):
        svc.review_rule_hold(first["rule_id"], first_new["version_id"])
    with pytest.raises(SwitchboardError):
        svc.review_rule_hold(first["rule_id"], first["version_id"], confirmed=True)
    result = svc.review_rule_hold(first["rule_id"], first_new["version_id"], confirmed=True)
    assert result["released"]
    assert svc.held_rule_ids("reports") == {other["rule_id"]}
    assert svc.store.query_one("SELECT count(*) AS n FROM feedback_labels")["n"] == 0
    assert all(h["fresh_count"] == 0 for h in svc.list_holds())
    assert ask(svc, agent, "reviewed")["decision"] == "answer"


def test_review_cannot_resume_an_incomplete_scope_contract(setup):
    svc, _ = setup
    made = rule(svc)
    latest = svc.supersede_rule(made["rule_id"], new_answer={"value": "pdf"})
    svc.set_scope_contract("reports", ["project", "workspace"])
    with pytest.raises(SwitchboardError):
        svc.review_rule_hold(made["rule_id"], latest["version_id"], confirmed=True)
    assert svc.held_rule_ids("reports") == {made["rule_id"]}
