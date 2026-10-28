import { useState } from "react";
import { api } from "../api";
import type { EvalReport, EvalRow } from "../types";

const LABELS: Record<string, string> = {
  B0_static: "B0 · static",
  B1_generic: "B1 · generic adaptive",
  B2_supersession: "B2 · supersession (proposed)",
  B3_integrity: "B3 · supersession + integrity",
  ablation_no_boundary: "ablation · no boundary checks",
  ablation_no_dependency: "ablation · no dependency tracking",
};

function Row({ r }: { r: EvalRow }) {
  return (
    <tr>
      <td className="strat">{LABELS[r.strategy] ?? r.strategy}</td>
      <td>{r.total}</td>
      <td>{(r.coverage * 100).toFixed(0)}%</td>
      <td>{r.interruptions_deferred}</td>
      <td className={r.wrong_auto > 0 ? "bad" : "good"}>{r.wrong_auto}</td>
      <td>
        {(r.wrong_auto_rate * 100).toFixed(1)}%
        <span className="ci">
          [{(r.wrong_auto_ci95[0] * 100).toFixed(1)}–{(r.wrong_auto_ci95[1] * 100).toFixed(1)}]
        </span>
      </td>
      <td className={r.stale_after_flip > 0 ? "bad" : "good"}>{r.stale_after_flip}</td>
      <td className={r.out_of_scope_auto > 0 ? "bad" : "good"}>{r.out_of_scope_auto}</td>
      <td>{r.blast_radius_recall === null ? "—" : r.blast_radius_recall.toFixed(2)}</td>
    </tr>
  );
}

export default function EvaluationPanel() {
  const [report, setReport] = useState<EvalReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setReport(await api.runEvaluation());
    } catch {
      setError("Replay failed. No results were fabricated.");
    }
    setBusy(false);
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Replay evaluation</h2>
        <button className="primary" disabled={busy} onClick={run}>
          {busy ? "Running…" : "Run baseline comparison"}
        </button>
      </div>
      <p className="prose" style={{ marginTop: 0 }}>
        Same synthetic preference-flip traces for every method. Each category learns a rule,
        the preference flips mid-stream, and we count what each strategy does next.
      </p>
      {error && <div className="empty">{error}</div>}
      {report && (
        <>
          <div style={{ overflowX: "auto" }}>
            <table className="eval">
              <thead>
                <tr>
                  <th>Method</th>
                  <th>Questions</th>
                  <th>Coverage</th>
                  <th>Deferrals</th>
                  <th>Wrong auto</th>
                  <th>Wrong-auto rate [95% CI]</th>
                  <th>Stale after flip</th>
                  <th>Out-of-scope auto</th>
                  <th>Blast recall</th>
                </tr>
              </thead>
              <tbody>
                {report.strategies.map((r) => (
                  <Row key={r.strategy} r={r} />
                ))}
                {report.ablations.map((r) => (
                  <Row key={r.strategy} r={r} />
                ))}
              </tbody>
            </table>
          </div>
          {report.stress && report.stress.length > 0 && (
            <>
              <h2 style={{ marginTop: 18 }}>Stress suites (B1 vs B2)</h2>
              <div style={{ overflowX: "auto" }}>
                <table className="eval">
                  <thead>
                    <tr>
                      <th>Suite</th>
                      <th>Method</th>
                      <th>Coverage</th>
                      <th>Wrong auto</th>
                      <th>Out-of-scope auto</th>
                      <th>Deferrals</th>
                      <th>Label contamination</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.stress.map((r) => (
                      <tr key={r.suite + r.strategy}>
                        <td className="strat">{r.suite.replace(/_/g, " ")}</td>
                        <td>{LABELS[r.strategy] ?? r.strategy}</td>
                        <td>{(r.coverage * 100).toFixed(0)}%</td>
                        <td className={r.wrong_auto > 0 ? "bad" : "good"}>{r.wrong_auto}</td>
                        <td className={r.out_of_scope_auto > 0 ? "bad" : "good"}>{r.out_of_scope_auto}</td>
                        <td>{r.interruptions_deferred}</td>
                        <td className={(r.label_contamination ?? 0) > 0 ? "bad" : "good"}>
                          {r.label_contamination ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="note">
                S2 (noisy first correction): the sliced hold defers the first wrong window, so
                fewer wrong autos than immediate resume. S1 (misscoped correction): both leak
                out of scope — a hold cannot fix a scope the system was never told. Recorded
                honestly, not hidden.
              </div>
            </>
          )}
          {report.episodes && (
            <>
              <h2 style={{ marginTop: 18 }}>Paired episodes (B1 vs B2)</h2>
              <div className="note" style={{ borderTop: "none", marginTop: 0 }}>
                {Object.entries(report.episodes).map(([name, a]) => (
                  <div key={name}>
                    {LABELS[name] ?? name}: {a.episodes} episodes · mean coverage{" "}
                    {(a.mean_coverage * 100).toFixed(0)}% · wrong auto {a.wrong_auto} ·
                    deferrals {a.deferrals} · mean recovery{" "}
                    {a.mean_recovery_questions ?? "—"} questions after a flip
                  </div>
                ))}
                <div>
                  Episodes are paired synthetic variants — smoke evidence, not population
                  estimates. Silent-drift suites are negative controls: with no supersession
                  event, no hold can help, and both arms go stale.
                </div>
              </div>
            </>
          )}
          <div className="note">
            {report.notes.map((n) => (
              <div key={n}>{n}</div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
