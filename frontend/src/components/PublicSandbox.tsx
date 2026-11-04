import { useState } from "react";

type Impact = { dependent_id: string | null; proposed_status: string };
type Preview = { current_version_id: string; changed: boolean; blast_radius: { affected: Impact[] } };

async function sample<T>(action: string, body: unknown = {}): Promise<T> {
  const response = await fetch(`/sandbox/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail ?? "The example could not update. Please retry.");
  return result as T;
}

export default function PublicSandbox({ onFocus, onManage, onChange, compact = false }: {
  onFocus: () => void; onManage: () => void; onChange: () => void; compact?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [changed, setChanged] = useState(false);
  const [resetting, setResetting] = useState(false);

  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "Please retry."); }
    finally { setBusy(false); }
  };
  const reuse = (differentProject = false) => run(async () => {
    const result = await sample<{ agent: string; decision: string; answer?: { value?: string }; reason_code: string }>(
      "reuse", { different_project: differentProject });
    setMessage(result.decision === "answer"
      ? `${result.agent} received “${result.answer?.value}” from the saved workshop rule. Its sample draft is now recorded.`
      : differentProject
        ? `${result.agent} asked about another project. The workshop answer stayed inside its limits; this question is waiting in the inbox.`
        : `${result.agent} is waiting for review. Check the inbox and the rule’s boundaries or correction hold.`);
    onChange();
  });
  const correct = () => run(async () => {
    if (!preview) return;
    await sample("correct", { expected_version_id: preview.current_version_id });
    setChanged(true); setPreview(null);
    setMessage("Sunday at 11 AM is saved. Recorded drafts need another check; only this changed rule pauses for review. Completed work is not undone.");
    onChange();
  });

  return (
    <section className={`sandbox-panel${compact ? " sandbox-compact" : ""}`} aria-label="Public playground">
      <div className="sandbox-heading">
        <div><span className="sandbox-label">PUBLIC PLAYGROUND · YOUR OWN EXAMPLE</span>
          {!compact && <h2>One workshop. Many assistants. You’re in control.</h2>}
        </div>
        <div className="sandbox-reset">
          {resetting ? <>
            <span>Start this example over?</span>
            <button disabled={busy} onClick={() => run(async () => { await sample("reset"); window.location.assign("/"); })}>Reset example</button>
            <button disabled={busy} onClick={() => setResetting(false)}>Keep exploring</button>
          </> : <button onClick={() => setResetting(true)}>Start over</button>}
        </div>
      </div>
      {!compact && <>
        <p className="sandbox-intro">Imagine you’re organising a photography workshop. Your sample assistants have used Saturday at 10 AM on a signup page and an invitation. Try sharing that answer, changing the plan, or handling the next question on your phone.</p>
        <div className="sandbox-steps">
          <div><span className="sandbox-step">01 · ANSWER IN FOCUS</span><h3>Handle what needs you.</h3>
            <p>Choose which contact details to include. A sample payment always needs a deliberate review.</p>
            <button onClick={onFocus}>Try Focus mode →</button>
          </div>
          <div><span className="sandbox-step">02 · SHARE AN ANSWER</span><h3>Keep assistants consistent.</h3>
            <p>Ask another sample assistant for the saved time. Then try a different project to see the boundary.</p>
            <div className="sandbox-actions"><button disabled={busy} onClick={() => reuse()}>Ask another assistant</button>
              <button disabled={busy} onClick={() => reuse(true)}>Try another project</button></div>
          </div>
          <div><span className="sandbox-step">03 · CHANGE YOUR MIND</span><h3>Find what needs updating.</h3>
            <p>Move the workshop to Sunday at 11 AM. Preview the recorded work affected before saving.</p>
            <div className="sandbox-actions"><button disabled={busy || changed} onClick={() => run(async () => {
              const result = await sample<Preview>("preview"); setPreview(result); setMessage("");
            })}>{changed ? "Correction saved" : "Preview Sunday at 11 AM"}</button>
              <button onClick={onManage}>Explore agents & rules</button></div>
          </div>
        </div>
        {preview && <div className="sandbox-preview">
          <strong>Proposed change: Sunday at 11 AM</strong>
          <ul>{preview.blast_radius.affected.map((item, i) => <li key={i}>
            {item.dependent_id ?? "Unrecorded work"} — {item.proposed_status === "revalidate" ? "check this unfinished draft again"
              : item.proposed_status === "review_completed" ? "review this completed draft" : item.proposed_status.replaceAll("_", " ")}
          </li>)}</ul>
          <p>Only recorded dependencies are shown. This change pauses reuse of this rule until it is reviewed.</p>
          <div className="sandbox-actions"><button className="primary" disabled={busy || !preview.changed} onClick={correct}>Save Sunday at 11 AM</button>
            <button disabled={busy} onClick={() => setPreview(null)}>Keep current time</button></div>
        </div>}
        {message && <p className="sandbox-result" role="status">{message}</p>}
        <p className="sandbox-note">Real Switchboard logic, fictional sample agents and choices. This disposable workspace expires after 30 minutes or a restart. No real payments, messages or deployments happen. Model calls and external connections are off. Please use sample data.</p>
      </>}
      {error && <p className="sandbox-result sandbox-error" role="alert">{error}</p>}
    </section>
  );
}
