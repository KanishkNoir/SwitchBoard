"""Reproducible synthetic service benchmark. No network, provider calls or live hub.

python -m switchboard.benchmark --output .tmp/results-current.json
The frozen input contains independent expected answers and work IDs/statuses.
"""
import argparse
import hashlib
import json
import platform
from importlib.metadata import version
from collections import Counter, defaultdict
from pathlib import Path

from .config import Settings
from .domain import QuestionRequest
from .matching import MatcherLadder
from .persistence import Store
from .service import SwitchboardService

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "benchmarks" / "scenarios.v1.json"
ARMS = ("always_ask", "immediate_resume", "switchboard", "no_scope", "no_dependencies")
ACTIONABLE = frozenset(("revalidate", "review_completed", "review_failed"))


def score_answer(expected, automatic, value):
    """A matching value cannot excuse answering across a must-review boundary."""
    correct_value = value == expected["value"]
    boundary_violation = automatic and expected["must_ask"]
    wrong = automatic and (not correct_value or boundary_violation)
    return {"queries": 1, "automatic": int(automatic), "reviews": int(not automatic),
            "eligible_queries": int(not expected["must_ask"]),
            "correct_reuse": int(automatic and not wrong), "wrong_auto": int(wrong),
            "boundary_violations": int(boundary_violation),
            "must_review": int(expected["must_ask"]),
            "required_reviews_observed": int(expected["must_ask"] and not automatic),
            "correct_delivered": int(correct_value),
            "stale_auto": int(automatic and not correct_value and
                              expected["reason"] == "unannounced_preference_change")}


def score_impact(expected, rows):
    """Match actual work IDs; unknown/unaffected rows are never positive detections."""
    wanted = {k for k, v in expected["statuses"].items() if v in ACTIONABLE}
    found = {r["dependent_id"] for r in rows if r.get("dependent_id") is not None
             and r["proposed_status"] in ACTIONABLE}
    # Exact ID/status pairs also grade unknown/unaffected controls and wrong status assignments.
    expected_pairs = set(expected["statuses"].items())
    actual_pairs = {(r["dependent_id"], r["proposed_status"]) for r in rows
                    if r.get("dependent_id") is not None}
    unknown_receipts = sum(r.get("dependent_id") is None and
                           r["proposed_status"] == "unknown_dependency_coverage" for r in rows)
    return {"true_positive": len(wanted & found), "false_positive": len(found - wanted),
            "false_negative": len(wanted - found), "expected_edges": len(wanted),
            "status_correct": len(expected_pairs & actual_pairs), "status_expected": len(expected_pairs),
            "unexpected_status_pairs": len(actual_pairs - expected_pairs),
            "unknown_receipts_expected": expected["unknown_receipts"],
            "unknown_receipts_observed": unknown_receipts,
            "unknown_count_checks_passed": int(unknown_receipts == expected["unknown_receipts"]),
            "checks": 1}


def isolated_service():
    # Explicit local ladder prevents provider access even if the parent process has credentials.
    cfg = Settings(db_path=":memory:", remote_url="", ui_token="", baseten_api_key="",
                   meta_api_key="", modal_chat_url="", modal_t2_url="", modal_image_url="",
                   modal_segmentation_url="", modal_proxy_token_id="", modal_proxy_token_secret="",
                   enable_t3=False, enable_image=False, enable_segmentation=False, risk_gate_mode="shadow")
    return SwitchboardService(Store(":memory:"), cfg=cfg, ladder=MatcherLadder(t1_threshold=0.35))


def run_episode(episode, arm):
    if arm not in ARMS:
        raise ValueError(f"unknown benchmark arm: {arm}")
    svc = isolated_service()
    try:
        agents = {}
        for alias in ("a", "b"):
            reg = svc.register_agent(f"synthetic-{alias}", "benchmark_fixture")
            agents[alias] = svc.authenticate(reg["api_key"])
        rules = {}
        for rule in episode["rules"]:
            made = svc.create_rule(rule["category"], rule["predicate"], rule["answer"],
                                   scope={} if arm == "no_scope" else rule["scope"],
                                   source_type="synthetic", actor="synthetic_fixture")
            rules[rule["id"]] = (made["rule_id"], rule["category"])
            svc.set_stage(rule["category"], "shadow" if arm == "always_ask" else "auto",
                          reason="synthetic_fixture_manual_stage")
        totals, impacts = Counter(), Counter()
        trace, failures = [], []
        for index, step in enumerate(episode["steps"]):
            if step["op"] == "correct":
                rid, category = rules[step["rule"]]
                svc.supersede_rule(rid, new_answer=step["answer"], actor="synthetic_fixture")
                if arm == "immediate_resume":
                    svc.clear_holds(category, actor="synthetic_fixture_hold_ablation")
                entry = {"step": index, "op": "correct", "answer": step["answer"]}
                if "impact" in step and arm != "always_ask":
                    rows = svc.blast_radius(rid)["affected"]
                    observed = [{"dependent_id": r.get("dependent_id"), "proposed_status": r["proposed_status"]}
                                for r in rows]
                    observed.sort(key=lambda r: (r["dependent_id"] or "", r["proposed_status"]))
                    scored = score_impact(step["impact"], observed)
                    impacts.update(scored)
                    entry.update(expected=step["impact"], observed=observed, score=scored)
                    if (scored["false_positive"] or scored["false_negative"]
                            or scored["status_correct"] != scored["status_expected"]
                            or scored["unexpected_status_pairs"] or not scored["unknown_count_checks_passed"]):
                        failures.append({"step": index, "reason": "impact_mismatch", "score": scored})
                trace.append(entry)
                continue
            agent = agents[step["agent"]]
            resp = svc.ask(agent, QuestionRequest(
                request_id=f"{episode['id']}.{index}", question=step["question"], category=step["category"],
                context=step["context"], intent_type=step["intent_type"], reversibility=step["reversibility"],
                action=step.get("action")))
            automatic = resp["decision"] == "answer"
            entry = {"step": index, "op": "ask", "id": step["id"], "agent": step["agent"],
                     "decision": resp["decision"], "expected": step["expected"]}
            if step.get("flood"):
                holds_before = [(h["fresh_count"], h["status"]) for h in svc.list_holds(step["category"])]
                accepted = sum(svc.report_outcome(agent, resp["decision_id"], "success",
                                                   detail="synthetic adversarial claim")["eligible_for_calibration"]
                               for _ in range(step["flood"]))
                holds_after = [(h["fresh_count"], h["status"]) for h in svc.list_holds(step["category"])]
                invariant = accepted == 0 and holds_before == holds_after
                totals.update({"agent_claims": step["flood"], "agent_claims_eligible": accepted,
                               "evidence_checks": 1, "evidence_checks_passed": int(invariant)})
                entry["agent_claim_check_passed"] = invariant
                if not invariant:
                    failures.append({"step": step["id"], "reason": "agent_claim_contamination"})
            if automatic:
                value = (resp["answer"] or {}).get("value")
                if "work" in step and arm != "no_dependencies":
                    work = step["work"]
                    svc.record_use(agent, resp["receipt_id"], "benchmark_artifact", work["id"],
                                   "uses_answer", status=work["status"])
            else:
                # Same authored oracle is available to EVERY arm, only when review is requested.
                item = next(i for i in svc.inbox() if i["question_id"] == resp["question_id"])
                svc.answer_inbox(item["id"], {"value": step["expected"]["value"]}, actor="synthetic_oracle")
                # Verify retrieval, rather than assuming a submitted answer reached the agent.
                delivered = svc.action_request_status(agent, resp["question_id"], expected_intent=None)
                value = (delivered.get("answer") or {}).get("value")
                if delivered["status"] != "answered":
                    value = {"error": "human_answer_not_retrievable"}
            score = score_answer(step["expected"], automatic, value)
            totals.update(score)
            entry.update(value=value, score=score)
            if score["wrong_auto"] or not score["correct_delivered"]:
                failures.append({"step": step["id"], "reason": step["expected"]["reason"],
                                 "expected_value": step["expected"]["value"], "value": value})
            trace.append(entry)
        return {"episode": episode["id"], "family": episode["family"], "domain": episode["domain"],
                "counts": dict(totals), "impact": dict(impacts), "failures": failures,
                "passed": not failures, "trace": trace}
    finally:
        svc.store.close()


def summarize(episodes):
    totals, impacts = Counter(), Counter()
    for ep in episodes:
        totals.update(ep["counts"])
        impacts.update(ep["impact"])
    def rate(num, den):
        return round(num / den, 6) if den else None
    t, i = totals, impacts
    return {"episodes": len(episodes), "episodes_passed": sum(ep["passed"] for ep in episodes),
            "counts": dict(t), "rates": {
                "automatic_coverage": rate(t["automatic"], t["queries"]),
                "auto_precision": rate(t["correct_reuse"], t["automatic"]),
                "eligible_correct_reuse": rate(t["correct_reuse"], t["eligible_queries"]),
                "required_review_recall": rate(t["required_reviews_observed"], t["must_review"])},
            "impact": {**dict(i), "precision": rate(i["true_positive"], i["true_positive"] + i["false_positive"]),
                       "recall": rate(i["true_positive"], i["expected_edges"]),
                       "status_accuracy": rate(i["status_correct"], i["status_expected"])}}


def code_fingerprint():
    # Include the implementation under evaluation, not only the runner.
    files = sorted((ROOT / "switchboard").rglob("*.py"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def run_benchmark(dataset_path=DEFAULT_DATASET):
    raw = Path(dataset_path).read_bytes()
    dataset = json.loads(raw)
    if dataset["schema_version"] != 1:
        raise ValueError("unsupported benchmark dataset schema")
    reports = {}
    for arm in ARMS:
        episodes = [run_episode(ep, arm) for ep in dataset["episodes"]]
        families = defaultdict(list)
        for ep in episodes:
            families[ep["family"]].append(ep)
        reports[arm] = {"summary": summarize(episodes),
                        "by_family": {k: summarize(v) for k, v in sorted(families.items())},
                        "episodes": episodes}
    return {"schema_version": 1, "is_synthetic": True, "dataset_id": dataset["dataset_id"],
            "dataset_sha256": hashlib.sha256(raw).hexdigest(), "python_version": platform.python_version(),
            "service_code_sha256": code_fingerprint(),
            "dependencies": {name: version(name) for name in ("mcp", "fastapi", "httpx", "pydantic")},
            "configuration": {"store": ":memory: per episode/arm", "risk_gate_mode": "shadow",
                              "stages": "manual auto; always_ask uses shadow", "matcher": "local T0/T1",
                              "t1_threshold": 0.35, "external_model_calls": False,
                              "human_feedback": "synthetic oracle via answer_inbox on every deferral",
                              "native_assistant_execution": False},
            "arms": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, help="also write a compact, generated results table")
    args = parser.parse_args()
    report = run_benchmark(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        json_link = args.output.resolve().relative_to(args.markdown.parent.resolve(), walk_up=True).as_posix()
        args.markdown.write_text(markdown_report(report, json_link=json_link), encoding="utf-8")
    for arm, result in report["arms"].items():
        s, c = result["summary"], result["summary"]["counts"]
        print(f"{arm}: queries={c['queries']} correct_reuse={c['correct_reuse']} "
              f"wrong_auto={c['wrong_auto']} reviews={c['reviews']} "
              f"episodes_passed={s['episodes_passed']}/{s['episodes']}")


def markdown_report(report, json_link="results.v1.json"):
    lines = ["# Synthetic service benchmark results", "",
             f"Generated from [{json_link}]({json_link}). See [method and limits](README.md).", "",
             "Each arm receives 40 correlated episodes, 220 questions: 160 eligible for reuse and 60 requiring review.", "",
             "| Arm | Correct automatic reuse / 160 eligible | Wrong automatic decisions / 220 queries | Reviews / 220 queries | Episodes passed / 40 |",
             "|---|---:|---:|---:|---:|"]
    for arm, data in report["arms"].items():
        s, c = data["summary"], data["summary"]["counts"]
        lines.append(f"| {arm} | {c['correct_reuse']} | {c['wrong_auto']} | {c['reviews']} | {s['episodes_passed']} |")
    lines.extend(["", "Wrong automatic decisions include correct values returned across a must-review boundary.", "",
                  "## Full Switchboard by condition family", "",
                  "| Family | Queries | Correct automatic reuse | Wrong automatic decisions | Reviews | Episodes passed / 5 |",
                  "|---|---:|---:|---:|---:|---:|"])
    for family, s in report["arms"]["switchboard"]["by_family"].items():
        c = s["counts"]
        lines.append(f"| {family} | {c['queries']} | {c['correct_reuse']} | {c['wrong_auto']} | {c['reviews']} | {s['episodes_passed']} |")
    lines.extend(["", "## Correction impact", "",
                  "| Arm | Found / 15 affected work IDs | False alarms | Correct / 50 ID-status pairs | Unknown-coverage count checks / 10 |",
                  "|---|---:|---:|---:|---:|"])
    for arm, data in report["arms"].items():
        i = data["summary"]["impact"]
        if not i.get("checks"):
            lines.append(f"| {arm} | n/a | n/a | n/a | n/a |")
        else:
            lines.append(f"| {arm} | {i['true_positive']} | {i['false_positive']} | {i['status_correct']} | {i['unknown_count_checks_passed']} |")
    lines.extend(["", "Always-ask has no rule-backed automatic work to invalidate, so impact scoring is not applicable.", "",
                  f"Dataset SHA-256: `{report['dataset_sha256']}`.", "",
                  f"Service source SHA-256: `{report['service_code_sha256']}`.", "",
                  "These are synthetic service tests with local T0/T1 matching and the risk gate in shadow mode. "
                  "They do not measure native assistant compliance, model reasoning, user time saved, or a production error rate.", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    main()
