"""Author the frozen v1 synthetic fixtures; never called by the benchmark runner.

Five domains crossed with eight condition families, not 40 independent users.
Expected answers, boundaries and work IDs are authored without querying the SUT.
"""
import copy
import json
from pathlib import Path


DOMAINS = [
    ("reports", "report format", "Which report format should this draft use?", "markdown", "pdf", "csv"),
    ("coding", "indent style", "Which indent style should this patch use?", "spaces", "tabs", "mixed"),
    ("scheduling", "meeting timezone", "Which meeting timezone should this plan use?", "UTC", "IST", "PST"),
    ("writing", "draft tone", "Which draft tone should this summary use?", "concise", "friendly", "formal"),
    ("charts", "chart units", "Which chart units should this preview use?", "metric", "imperial", "native"),
]


def build():
    episodes = []
    for domain, phrase, text, old, new, bad in DOMAINS:
        category = f"bench_{domain}"
        context = {"project": "atlas", "workspace": domain}
        scope = {"mandatory": context}
        predicate = {"keywords": phrase.split(), "example_question": text, "intent_type": "preference"}
        rule = {"id": "main", "category": category, "predicate": predicate,
                "answer": {"value": old}, "scope": scope}

        def ask(id, value=old, must_ask=False, reason="saved_preference", **kwargs):
            return {"op": "ask", "id": id, "agent": "a" if len(id) % 2 else "b",
                    "question": text, "category": category, "context": copy.deepcopy(context),
                    "intent_type": "preference", "reversibility": "reversible",
                    "expected": {"value": value, "must_ask": must_ask, "reason": reason}, **kwargs}

        def correction(value, **extra):
            return {"op": "correct", "rule": "main", "answer": {"value": value}, **extra}

        def episode(family, steps, rules=None):
            episodes.append({"id": f"{domain}.{family}", "domain": domain, "family": family,
                             "rules": copy.deepcopy(rules or [rule]), "steps": steps})

        episode("stable_reuse", [
            ask("initial", agent="a"), ask("second_agent", agent="b"),
            ask("paraphrase", question=f"For this task, please choose the {phrase}."),
            ask("repeated", agent="a"),
        ])
        episode("scope_boundaries", [
            ask("in_scope"),
            ask("other_project", must_ask=True, reason="scope_mismatch",
                context={**context, "project": "boreal"}),
            ask("missing_project", must_ask=True, reason="missing_scope", context={"workspace": domain}),
            ask("other_workspace", must_ask=True, reason="scope_mismatch",
                context={**context, "workspace": "external"}),
            ask("missing_workspace", must_ask=True, reason="missing_scope", context={"project": "atlas"}),
            ask("back_in_scope", agent="b"),
        ])
        episode("intent_boundaries", [
            ask("preference"),
            ask("permission", must_ask=True, reason="intent_mismatch", intent_type="permission"),
            ask("disambiguation", must_ask=True, reason="intent_mismatch", intent_type="disambiguation"),
            ask("unknown_category", must_ask=True, reason="no_saved_rule", category=category + "_unseen"),
        ])
        other = {**copy.deepcopy(rule), "id": "other", "category": category + "_other"}
        pre = [ask("work_" + status, work={"id": status, "status": status})
               for status in ("pending", "completed", "failed", "unaffected", "unknown")]
        pre += [ask("unrecorded"), ask("unrelated_work", category=other["category"],
                                      work={"id": "unrelated", "status": "pending"})]
        # Expected work IDs/statuses are literal external oracles, not copied from blast_radius.
        unchanged = {s: "unknown_dependency_coverage" if s == "unknown" else "unaffected"
                     for s in ("pending", "completed", "failed", "unaffected", "unknown")}
        changed = {"pending": "revalidate", "completed": "review_completed", "failed": "review_failed",
                   "unaffected": "unaffected", "unknown": "unknown_dependency_coverage"}
        episode("correction_dependencies", pre + [
            correction(old, impact={"statuses": unchanged, "unknown_receipts": 1}),
            correction(new, impact={"statuses": changed, "unknown_receipts": 1}),
            ask("after_correction", value=new), ask("after_review", value=new, agent="b"),
        ], rules=[rule, other])
        episode("noisy_correction", [
            ask("before"), correction(bad),
            ask("wrong_update_1", value=new, reason="wrong_correction"),
            ask("wrong_update_2", value=new, reason="wrong_correction"),
            ask("wrong_update_3", value=new, reason="wrong_correction"),
            correction(new), ask("repaired", value=new), ask("reused", value=new, agent="b"),
        ])
        episode("hard_locks", [
            ask("ordinary"),
            ask("money", must_ask=True, reason="hard_lock", context={**context, "money_movement": True}),
            ask("delete", must_ask=True, reason="hard_lock", action={"type": "delete"}),
            ask("new_recipient", must_ask=True, reason="hard_lock", context={**context, "new_recipient": True}),
            ask("irreversible", must_ask=True, reason="hard_lock", intent_type="action_review",
                reversibility="irreversible"),
        ])
        semantic_rule = copy.deepcopy(rule)
        semantic_rule["predicate"].pop("keywords")
        episode("evidence_integrity", [
            ask("before"), correction(new),
            ask("fresh_1", value=new, flood=25),
            ask("duplicate_context", value=new, flood=25),
            ask("fresh_2", value=new, context={**context, "task": "two"}),
            ask("fresh_3", value=new, context={**context, "task": "three"}),
            ask("resumed", value=new, agent="b"),
        ], rules=[semantic_rule])
        # Deliberately bad scope authoring + unannounced preference drift: expected failures.
        broad_rule = {**copy.deepcopy(rule), "scope": {"mandatory": {"workspace": domain}}}
        episode("negative_controls", [
            ask("baseline"),
            ask("bad_authored_scope", must_ask=True, reason="underspecified_rule_scope",
                context={**context, "project": "boreal"}),
            ask("silent_change_1", value=new, reason="unannounced_preference_change"),
            ask("silent_change_2", value=new, reason="unannounced_preference_change"),
        ], rules=[broad_rule])
    return {"schema_version": 1, "dataset_id": "switchboard-synthetic-v1",
            "label_source": "authored_synthetic_oracle",
            "design": "5 domains x 8 condition families; correlated controlled fixtures, not independent users",
            "episodes": episodes}


if __name__ == "__main__":
    Path(__file__).with_name("scenarios.v1.json").write_text(
        json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
