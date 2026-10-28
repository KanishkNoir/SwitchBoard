"""Replay evaluation (LLD 10 / Stage 8). Synthetic cases are always labeled synthetic.

Strategies:
  B0 static        — preference flip is ignored; the old rule keeps answering.
  B1 generic       — rule superseded, automation resumes immediately (no hold).
  B2 supersession  — supersede + recalibration hold until m fresh human answers.
  B3 integrity     — B2 plus evidence-integrity quarantine (same trace outcomes here;
                     the difference is which labels may enter calibration).
Ablations: B2 without scope predicates (no_boundary), B2 without dependency
tracking (blast-radius recall forced to 0 — nothing was recorded).
"""
import math

from .domain import QuestionRequest
from .persistence import Store
from .service import SwitchboardService

RECOVERY_M = 2  # fresh human answers required to clear a recalibration hold (demo default)


def wilson_interval(successes: int, n: int, z: float = 1.96):
    if n == 0:
        return [0.0, 1.0]
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def _run(cases, strategy: str, strip_scope: bool = False) -> dict:
    store = Store(":memory:")
    svc = SwitchboardService(store)
    reg = svc.register_agent("replay", "evaluation")
    agent = svc.authenticate(reg["api_key"])
    total = auto = wrong = deferred = stale = oos_auto = 0
    blast_expected = blast_found = 0
    recovery_samples = []
    for case in cases:
        cat = case["category"]
        rule = case["rule"]
        svc.create_rule(cat, rule["predicate"], rule["answer"],
                        scope=None if strip_scope else rule.get("scope"),
                        source_type="synthetic")
        svc.set_stage(cat, "auto", reason="replay")
        flipped = False
        fresh = 0
        since_flip = None
        recovered = False
        pre_flip_value = rule["answer"].get("value")
        for qi, q in enumerate(case["questions"]):
            if q.get("refix_answer") and strategy != "B0_static":
                rid2 = store.query_one("SELECT id FROM rules WHERE category=?", (cat,))["id"]
                svc.supersede_rule(rid2, new_answer=q["refix_answer"],
                                   new_scope=q.get("refix_scope"))
                if strategy == "B1_generic":
                    svc.clear_holds(cat)
            if q.get("silent_flip"):
                flipped = True  # gold moved, system was never told (S5 negative control)
                if since_flip is None:
                    since_flip = 0
            if q.get("after_flip") and not flipped:
                flipped = True
                fresh = 0
                since_flip = 0
                if strategy != "B0_static":
                    rid = store.query_one("SELECT id FROM rules WHERE category=?", (cat,))["id"]
                    svc.supersede_rule(rid, new_answer=case["flip_answer"],
                                       new_scope=case.get("flip_scope"))
                    blast_expected += 1
                    after = svc.blast_radius(rid)
                    if after["affected"]:
                        blast_found += 1
                    if strategy == "B1_generic":
                        svc.clear_holds(cat)  # immediate resume, no recalibration hold
            resp = svc.ask(agent, QuestionRequest(
                request_id=f"{cat}-{strategy}-{total}-{qi}", question=q["text"], category=cat,
                context=q.get("context", {}), intent_type="preference"))
            total += 1
            if since_flip is not None and not recovered:
                since_flip += 1
            if resp["decision"] == "answer":
                auto += 1
                value = (resp["answer"] or {}).get("value")
                if value != q["gold_answer"]:
                    wrong += 1
                    if flipped and value == pre_flip_value:
                        stale += 1
                if q.get("out_of_scope"):
                    oos_auto += 1
                if since_flip is not None and not recovered and value == q["gold_answer"]:
                    recovery_samples.append(since_flip)
                    recovered = True
            else:
                deferred += 1
                # Simulated human answers through the REAL service path (answer_inbox),
                # which is what counts distinct fresh evidence toward hold release.
                if strategy in ("B2_supersession", "B3_integrity"):
                    item = next((i for i in svc.inbox() if i["question_id"] == resp["question_id"]), None)
                    if item:
                        svc.answer_inbox(item["id"], {"value": q["gold_answer"]})
    store.close()
    return {
        "strategy": strategy,
        "total": total,
        "auto_answered": auto,
        "coverage": round(auto / total, 4) if total else 0,
        "interruptions_deferred": deferred,
        "wrong_auto": wrong,
        "wrong_auto_rate": round(wrong / auto, 4) if auto else 0,
        "wrong_auto_ci95": wilson_interval(wrong, auto),
        "stale_after_flip": stale,
        "out_of_scope_auto": oos_auto,
        "blast_radius_recall": round(blast_found / blast_expected, 4) if blast_expected else None,
        "mean_recovery_questions": (round(sum(recovery_samples) / len(recovery_samples), 2)
                                    if recovery_samples else None),
        "is_synthetic": True,
    }


def run_replay(cases, strategy="supersession"):
    mapping = {"supersession": "B2_supersession", "static": "B0_static"}
    name = mapping.get(strategy, strategy)
    out = _run(cases, name)
    out["strategy"] = strategy
    out["auto"] = out["auto_answered"]
    out["deferred"] = out["interruptions_deferred"]
    return out


def default_suite():
    """Synthetic preference-flip suite: in-scope, out-of-scope twins, and a flip per category."""
    return [
        {"category": "deploy",
         "rule": {"predicate": {"keywords": ["deploy", "target"], "example_question": "Which deploy target?"},
                  "answer": {"option_id": "a", "value": "staging"},
                  "scope": {"mandatory": {"env": "staging"}}},
         "flip_answer": {"option_id": "b", "value": "canary"},
         "questions": [
             {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "staging"},
             {"text": "Which deploy target?", "context": {"env": "production"},
              "gold_answer": "staging", "out_of_scope": True},
             {"text": "Which deploy target?", "context": {"env": "staging"},
              "gold_answer": "canary", "after_flip": True},
             {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary"},
             {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary"},
             {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary"},
         ]},
        {"category": "notify",
         "rule": {"predicate": {"keywords": ["notify", "channel"], "example_question": "Which notify channel?"},
                  "answer": {"option_id": "a", "value": "email"},
                  "scope": {"mandatory": {"team": "core"}}},
         "flip_answer": {"option_id": "b", "value": "chat"},
         "questions": [
             {"text": "Which notify channel?", "context": {"team": "core"}, "gold_answer": "email"},
             {"text": "Which notify channel?", "context": {"team": "core"},
              "gold_answer": "chat", "after_flip": True},
             {"text": "Which notify channel?", "context": {"team": "core"}, "gold_answer": "chat"},
             {"text": "Which notify channel?", "context": {"team": "core"}, "gold_answer": "chat"},
             {"text": "Which notify channel?", "context": {"team": "core"}, "gold_answer": "chat"},
         ]},
    ]


def stress_suites():
    """S1 misscoped correction and S2 noisy (wrong, then corrected) correction."""
    s1 = [{"category": "deploy",
           "rule": {"predicate": {"keywords": ["deploy", "target"], "example_question": "Which deploy target?"},
                    "answer": {"option_id": "a", "value": "staging"},
                    "scope": {"mandatory": {"env": "staging"}}},
           # Correction is applied with an underspecified (empty) scope: intended
           # staging-only, but the system was never told. Latent gold says production must not auto.
           "flip_answer": {"option_id": "b", "value": "canary"},
           "flip_scope": {},
           "questions": [
               {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "staging"},
               {"text": "Which deploy target?", "context": {"env": "staging"},
                "gold_answer": "canary", "after_flip": True},
               {"text": "Which deploy target?", "context": {"env": "production"},
                "gold_answer": "__defer__", "out_of_scope": True},
               {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary"},
           ]}]
    s2 = [{"category": "deploy",
           "rule": {"predicate": {"keywords": ["deploy", "target"], "example_question": "Which deploy target?"},
                    "answer": {"option_id": "a", "value": "staging"},
                    "scope": {"mandatory": {"env": "staging"}}},
           "flip_answer": {"option_id": "x", "value": "wrong-value"},
           "questions": [
               {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "staging"},
               {"text": "Which deploy target?", "context": {"env": "staging"},
                "gold_answer": "canary", "after_flip": True},
               {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary"},
               {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary"},
               {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary",
                "refix_answer": {"option_id": "b", "value": "canary"}},
               {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary"},
               {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary"},
           ]}]
    return {"S1_misscoped_correction": s1, "S2_noisy_correction": s2}


def extra_suites():
    """Paraphrase, change-type, oscillating and silent-drift suites."""
    base_rule = {"predicate": {"keywords": ["deploy"], "example_question": "Which deploy target should I use?"},
                 "answer": {"option_id": "a", "value": "staging"},
                 "scope": {"mandatory": {"env": "staging"}}}
    paraphrase = [{"category": "deploy", "rule": base_rule,
                   "flip_answer": {"option_id": "b", "value": "canary"},
                   "questions": [
                       {"text": "Which deploy target should I use?", "context": {"env": "staging"}, "gold_answer": "staging"},
                       {"text": "Where should this deploy go?", "context": {"env": "staging"},
                        "gold_answer": "canary", "after_flip": True},
                       {"text": "Pick the deployment destination for me", "context": {"env": "staging"}, "gold_answer": "canary"},
                       {"text": "Which deploy target should I use?", "context": {"env": "staging"}, "gold_answer": "canary"},
                   ]}]
    narrowing = [{"category": "deploy",
                  "rule": {"predicate": {"keywords": ["deploy", "target"], "example_question": "Which deploy target?"},
                           "answer": {"option_id": "a", "value": "staging"}, "scope": {}},
                  "flip_answer": {"option_id": "b", "value": "canary"},
                  "flip_scope": {"mandatory": {"env": "staging"}},
                  "questions": [
                      {"text": "Which deploy target?", "context": {"env": "production"}, "gold_answer": "staging"},
                      {"text": "Which deploy target?", "context": {"env": "staging"},
                       "gold_answer": "canary", "after_flip": True},
                      {"text": "Which deploy target?", "context": {"env": "production"},
                       "gold_answer": "__defer__", "out_of_scope": True},
                      {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary"},
                  ]}]
    oscillating = [{"category": "deploy", "rule": base_rule,
                    "flip_answer": {"option_id": "b", "value": "canary"},
                    "questions": [
                        {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "staging"},
                        {"text": "Which deploy target?", "context": {"env": "staging"},
                         "gold_answer": "canary", "after_flip": True},
                        {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary"},
                        {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "staging",
                         "refix_answer": {"option_id": "a", "value": "staging"}},
                        {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "staging"},
                        {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "staging"},
                    ]}]
    silent = [{"category": "deploy", "rule": base_rule,
               "flip_answer": {"option_id": "b", "value": "canary"},
               "questions": [
                   {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "staging"},
                   {"text": "Which deploy target?", "context": {"env": "staging"},
                    "gold_answer": "canary", "silent_flip": True},
                   {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary"},
                   {"text": "Which deploy target?", "context": {"env": "staging"}, "gold_answer": "canary"},
               ]}]
    return {"S_paraphrase": paraphrase, "S4_scope_narrowing": narrowing,
            "S6_oscillating": oscillating, "S5_silent_drift": silent}


def _run_s3(naive: bool) -> dict:
    """Adversarial agent labels during the hold (B3's falsifiable test).

    The first correction is wrong (like S2). An agent then floods report_outcome
    claiming success. A naive arm that counts agent labels as fresh evidence
    releases the hold early and auto-answers the wrong rule more; B3 (production
    service) never counts them.
    """
    store = Store(":memory:")
    svc = SwitchboardService(store)
    reg = svc.register_agent("adversary", "agent")
    agent = svc.authenticate(reg["api_key"])
    svc.create_rule("deploy", {"keywords": ["deploy", "target"], "example_question": "Which deploy target?"},
                    {"value": "staging"}, scope={"mandatory": {"env": "staging"}}, source_type="synthetic")
    svc.set_stage("deploy", "auto")
    golds = ["staging", "canary", "canary", "canary", "canary", "canary"]
    wrong = auto = deferred = 0
    contamination = 0
    flipped = False
    for i, gold in enumerate(golds):
        if i == 1 and not flipped:
            flipped = True
            rid = store.query_one("SELECT id FROM rules WHERE category='deploy'")["id"]
            svc.supersede_rule(rid, new_answer={"value": "wrong-value"})
            # naive arm does NOT clear here: it releases when the agent flood
            # is (incorrectly) counted as fresh evidence below.
        resp = svc.ask(agent, QuestionRequest(
            request_id=f"s3-{naive}-{i}", question="Which deploy target?", category="deploy",
            context={"env": "staging"}, intent_type="preference"))
        if resp["decision"] == "answer":
            auto += 1
            if (resp["answer"] or {}).get("value") != gold:
                wrong += 1
        else:
            deferred += 1
            # Adversary floods agent-asserted outcomes on the deferred decision.
            for k in range(3):
                svc.report_outcome(agent, resp["decision_id"], "success", f"agent flood {k}")
            if naive:
                contamination += 3
                svc._record_fresh_evidence("deploy", {"env": "staging", "flood": i}, "agent_asserted_naive")
            else:
                svc.answer_inbox(
                    next(x for x in svc.inbox() if x["question_id"] == resp["question_id"])["id"],
                    {"value": gold})
        if i == 3:
            rid = store.query_one("SELECT id FROM rules WHERE category='deploy'")["id"]
            svc.supersede_rule(rid, new_answer={"value": "canary"})
            if naive:
                svc.clear_holds("deploy")
    store.close()
    return {"suite": "S3_adversarial_labels",
            "strategy": "B2_naive_counts_agent_labels" if naive else "B3_integrity",
            "total": len(golds), "auto_answered": auto,
            "coverage": round(auto / len(golds), 4), "interruptions_deferred": deferred,
            "wrong_auto": wrong, "wrong_auto_rate": round(wrong / auto, 4) if auto else 0,
            "wrong_auto_ci95": wilson_interval(wrong, auto),
            "stale_after_flip": 0, "out_of_scope_auto": 0, "blast_radius_recall": None,
            "mean_recovery_questions": None, "label_contamination": contamination,
            "is_synthetic": True}


def run_stress() -> list:
    out = []
    for suite_name, cases in {**stress_suites(), **extra_suites()}.items():
        for strategy in ("B1_generic", "B2_supersession"):
            row = _run(cases, strategy)
            out.append({"suite": suite_name, **row})
    out.append(_run_s3(naive=False))
    out.append(_run_s3(naive=True))
    return out


def _episode_cases(ep: int):
    envs = ["staging", "qa", "dev", "sandbox"]
    env = envs[ep % len(envs)]
    texts = ["Which deploy target?", "Where should this deploy go?", "Which deploy target should I use?"]
    return [{"category": f"deploy-{ep}",
             "rule": {"predicate": {"keywords": ["deploy"], "example_question": "Which deploy target should I use?"},
                      "answer": {"option_id": "a", "value": "staging"},
                      "scope": {"mandatory": {"env": env}}},
             "flip_answer": {"option_id": "b", "value": "canary"},
             "questions": [
                 {"text": texts[ep % 3], "context": {"env": env}, "gold_answer": "staging"},
                 {"text": texts[(ep + 1) % 3], "context": {"env": env},
                  "gold_answer": "canary", "after_flip": True},
                 {"text": texts[(ep + 2) % 3], "context": {"env": env}, "gold_answer": "canary"},
                 {"text": texts[ep % 3], "context": {"env": env}, "gold_answer": "canary"},
                 {"text": texts[(ep + 1) % 3], "context": {"env": "other"},
                  "gold_answer": "__defer__", "out_of_scope": True},
             ]}]


def run_episodes(n: int = 6) -> dict:
    """Paired multi-episode runs (same episodes under B1 and B2) with aggregates."""
    agg = {}
    for ep in range(n):
        cases = _episode_cases(ep)
        for strategy in ("B1_generic", "B2_supersession"):
            row = _run(cases, strategy)
            a = agg.setdefault(strategy, {"episodes": 0, "coverage": [], "wrong_auto": 0,
                                          "deferrals": 0, "recovery": []})
            a["episodes"] += 1
            a["coverage"].append(row["coverage"])
            a["wrong_auto"] += row["wrong_auto"]
            a["deferrals"] += row["interruptions_deferred"]
            if row["mean_recovery_questions"] is not None:
                a["recovery"].append(row["mean_recovery_questions"])
    for a in agg.values():
        a["mean_coverage"] = round(sum(a["coverage"]) / len(a["coverage"]), 4) if a["coverage"] else 0
        a["mean_recovery_questions"] = (round(sum(a["recovery"]) / len(a["recovery"]), 2)
                                        if a["recovery"] else None)
        a["note"] = "Episodes are paired synthetic variants; treat as smoke evidence, not population estimates."
    return agg


def run_comparison(cases=None) -> dict:
    cases = cases or default_suite()
    strategies = [_run(cases, s) for s in
                  ("B0_static", "B1_generic", "B2_supersession", "B3_integrity")]
    ablations = [
        {**_run(cases, "B2_supersession", strip_scope=True), "strategy": "ablation_no_boundary"},
        {**_run(cases, "B2_supersession"), "strategy": "ablation_no_dependency",
         "blast_radius_recall": 0.0, "note": "no record_use edges were kept, so impact is unknown"},
    ]
    return {
        "strategies": strategies,
        "ablations": ablations,
        "stress": run_stress(),
        "episodes": run_episodes(),
        "is_synthetic": True,
        "notes": [
            "All traces are synthetic and labeled as such; they are not real user evidence.",
            "Wrong-auto rates are historical measurements on this suite with 95% Wilson intervals — not a population guarantee.",
            "B3 differs from B2 in label eligibility (agent/model labels quarantined), which does not change outcomes on this trace suite.",
            "Repeated questions from one synthetic user are correlated; intervals treat them as independent and are therefore optimistic.",
        ],
    }
