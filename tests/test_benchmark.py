"""Independent scorer counterexamples; don't infer correctness from aggregate wins."""
import json
from copy import deepcopy

from switchboard.benchmark import (DEFAULT_DATASET, run_episode, score_answer,
                                   score_impact, summarize)


def test_matching_value_does_not_excuse_boundary_violation():
    expected = {"value": "markdown", "must_ask": True, "reason": "scope_mismatch"}
    score = score_answer(expected, True, "markdown")
    assert score["wrong_auto"] == score["boundary_violations"] == 1
    assert score["correct_reuse"] == score["required_reviews_observed"] == 0
    reviewed = score_answer(expected, False, "markdown")
    assert reviewed["wrong_auto"] == 0 and reviewed["required_reviews_observed"] == 1


def test_wrong_value_in_scope_is_wrong_auto():
    expected = {"value": "new", "must_ask": False, "reason": "wrong_correction"}
    assert score_answer(expected, True, "old")["wrong_auto"] == 1
    assert score_answer(expected, False, "old")["correct_delivered"] == 0


def test_unknown_coverage_is_not_an_impact_detection():
    expected = {"statuses": {"artifact": "revalidate"}, "unknown_receipts": 0}
    score = score_impact(expected, [{"dependent_id": None, "proposed_status": "unknown_dependency_coverage"}])
    assert score["true_positive"] == 0
    assert score["false_negative"] == 1
    assert score["unknown_count_checks_passed"] == 0


def test_wrong_dependency_id_creates_both_false_positive_and_false_negative():
    expected = {"statuses": {"real": "revalidate"}, "unknown_receipts": 0}
    score = score_impact(expected, [{"dependent_id": "wrong", "proposed_status": "revalidate"}])
    assert score["true_positive"] == 0
    assert score["false_positive"] == score["false_negative"] == 1


def test_correct_dependency_id_with_wrong_status_does_not_pass_status_grading():
    expected = {"statuses": {"real": "review_completed"}, "unknown_receipts": 0}
    score = score_impact(expected, [{"dependent_id": "real", "proposed_status": "revalidate"}])
    assert score["true_positive"] == 1
    assert score["status_correct"] == 0 and score["unexpected_status_pairs"] == 1


def test_unaffected_control_catches_overreporting():
    expected = {"statuses": {"unchanged": "unaffected"}, "unknown_receipts": 0}
    score = score_impact(expected, [{"dependent_id": "unchanged", "proposed_status": "revalidate"}])
    assert score["false_positive"] == 1 and score["status_correct"] == 0


def test_missing_denominators_are_null_not_perfect():
    summary = summarize([])
    assert all(value is None for value in summary["rates"].values())
    assert summary["impact"]["precision"] is summary["impact"]["recall"] is None


def test_frozen_dataset_has_balanced_families_and_authored_oracles():
    dataset = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    assert len(dataset["episodes"]) == 40
    assert len({ep["id"] for ep in dataset["episodes"]}) == 40
    families = {ep["family"] for ep in dataset["episodes"]}
    assert len(families) == 8
    for family in families:
        assert len({ep["domain"] for ep in dataset["episodes"] if ep["family"] == family}) == 5
    for ep in dataset["episodes"]:
        for step in ep["steps"]:
            if step["op"] == "ask":
                assert isinstance(step["expected"]["must_ask"], bool)
                assert step["expected"]["value"] is not None


def episode(family):
    return next(ep for ep in json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))["episodes"]
                if ep["family"] == family)


def test_service_impact_ablation_actually_omits_edges():
    fixture = episode("correction_dependencies")
    full = run_episode(fixture, "switchboard")
    omitted = run_episode(fixture, "no_dependencies")
    assert full["impact"]["true_positive"] == 3
    assert full["impact"]["false_positive"] == full["impact"]["false_negative"] == 0
    assert omitted["impact"]["true_positive"] == 0
    assert omitted["impact"]["false_negative"] == 3
    assert omitted["impact"]["unknown_receipts_observed"] > full["impact"]["unknown_receipts_observed"]


def test_oracle_answers_retrievable_in_always_ask_and_full_arms():
    fixture = episode("noisy_correction")
    for arm in ("always_ask", "switchboard"):
        result = run_episode(fixture, arm)
        assert result["counts"]["wrong_auto"] == 0
        assert result["counts"]["correct_delivered"] == result["counts"]["queries"]
    immediate = run_episode(fixture, "immediate_resume")
    assert immediate["counts"]["wrong_auto"] == 3


def test_expected_oracle_mutation_exposes_wrong_auto():
    fixture = deepcopy(episode("stable_reuse"))
    fixture["steps"][0]["expected"]["value"] = "deliberately_incorrect_saved_rule"
    result = run_episode(fixture, "switchboard")
    assert result["counts"]["wrong_auto"] == 1
    assert not result["passed"]


def test_agent_claim_flood_does_not_release_hold_or_count_as_gold():
    result = run_episode(episode("evidence_integrity"), "switchboard")
    counts = result["counts"]
    assert counts["agent_claims"] == 50
    assert counts["agent_claims_eligible"] == 0
    assert counts["evidence_checks"] == counts["evidence_checks_passed"] == 2
    # v1 uses only different task IDs to claim fresh contexts. Current policy
    # deliberately rejects this incidental metadata; keep the frozen data.
    assert counts["reviews"] == 5
    assert result["trace"][-1]["decision"] == "defer"
