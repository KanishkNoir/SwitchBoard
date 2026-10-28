from switchboard.evaluation import run_comparison, run_replay, wilson_interval


def test_wilson_interval_bounds():
    lo, hi = wilson_interval(0, 10)
    assert 0 <= lo <= hi <= 1
    assert wilson_interval(0, 0) == [0.0, 1.0]


def test_comparison_supersession_beats_static_on_flip():
    report = run_comparison()
    by = {s["strategy"]: s for s in report["strategies"]}
    assert report["is_synthetic"] is True
    # Static keeps answering with the stale pre-flip preference.
    assert by["B0_static"]["stale_after_flip"] > 0
    assert by["B0_static"]["wrong_auto"] > 0
    # Supersession holds automation until fresh evidence, so no stale autos.
    assert by["B2_supersession"]["stale_after_flip"] == 0
    assert by["B2_supersession"]["wrong_auto"] == 0
    # ...at the cost of more interruptions during recalibration.
    assert by["B2_supersession"]["interruptions_deferred"] > by["B1_generic"]["interruptions_deferred"]


def test_ablation_no_boundary_leaks_out_of_scope():
    report = run_comparison()
    by = {s["strategy"]: s for s in report["strategies"]}
    abl = {a["strategy"]: a for a in report["ablations"]}
    assert abl["ablation_no_boundary"]["out_of_scope_auto"] > by["B2_supersession"]["out_of_scope_auto"]
    assert by["B2_supersession"]["out_of_scope_auto"] == 0
    assert abl["ablation_no_dependency"]["blast_radius_recall"] == 0.0


def test_run_replay_backward_compatible_shape():
    cases = [{"category": "deploy",
              "rule": {"predicate": {"keywords": ["deploy", "target"], "example_question": "deploy target?"},
                       "answer": {"option_id": "a", "value": "staging"}},
              "flip_answer": {"option_id": "b", "value": "prod"},
              "questions": [{"text": "Which deploy target?", "gold_answer": "staging"},
                            {"text": "Which deploy target?", "gold_answer": "prod", "after_flip": True},
                            {"text": "Which deploy target?", "gold_answer": "prod"}]}]
    out = run_replay(cases, "supersession")
    assert out["is_synthetic"] is True and out["total"] == 3
