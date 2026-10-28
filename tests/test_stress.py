from switchboard.evaluation import run_stress


def test_stress_suites_run_and_differentiate():
    rows = {(r["suite"], r["strategy"]): r for r in run_stress()}
    s2_b1 = rows[("S2_noisy_correction", "B1_generic")]
    s2_b2 = rows[("S2_noisy_correction", "B2_supersession")]
    # The wrong first correction auto-answers more under immediate resume than under the hold.
    assert s2_b1["wrong_auto"] > s2_b2["wrong_auto"]
    # S1: a misscoped (scope-less) correction leaks out of scope under both — the hold
    # alone cannot fix a scope the system was never told. Recorded honestly.
    s1_b1 = rows[("S1_misscoped_correction", "B1_generic")]
    s1_b2 = rows[("S1_misscoped_correction", "B2_supersession")]
    assert s1_b1["out_of_scope_auto"] >= 1
    assert s1_b2["out_of_scope_auto"] >= 1
