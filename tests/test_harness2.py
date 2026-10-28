from switchboard.evaluation import run_episodes, run_stress


def rows():
    return {(r["suite"], r["strategy"]): r for r in run_stress()}


def test_s3_adversarial_labels_differentiate_b3():
    r = rows()
    naive = r[("S3_adversarial_labels", "B2_naive_counts_agent_labels")]
    b3 = r[("S3_adversarial_labels", "B3_integrity")]
    assert naive["label_contamination"] > 0
    assert b3["label_contamination"] == 0
    assert naive["wrong_auto"] >= b3["wrong_auto"]


def test_silent_drift_is_negative_control():
    r = rows()
    # No supersession ever happens, so hold machinery cannot help: stale autos occur.
    assert r[("S5_silent_drift", "B2_supersession")]["stale_after_flip"] > 0
    assert r[("S5_silent_drift", "B1_generic")]["stale_after_flip"] > 0


def test_paraphrase_and_narrowing_suites_run():
    r = rows()
    assert ("S_paraphrase", "B2_supersession") in r
    assert r[("S4_scope_narrowing", "B2_supersession")]["out_of_scope_auto"] == 0
    assert r[("S6_oscillating", "B1_generic")]["total"] == 6


def test_episodes_aggregate():
    agg = run_episodes(4)
    assert agg["B1_generic"]["episodes"] == 4
    assert agg["B2_supersession"]["mean_coverage"] <= agg["B1_generic"]["mean_coverage"]
    assert "mean_recovery_questions" in agg["B2_supersession"]
