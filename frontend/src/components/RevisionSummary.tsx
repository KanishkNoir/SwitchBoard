import { useState } from "react";
import { api } from "../api";
import type { SteeringSession } from "../types";

function changeLabel(session: SteeringSession): string {
  const latestNote = session.revisions[session.revisions.length - 1]?.note;
  if (latestNote?.startsWith("Sample agent:")) return "This sample draft stayed the same.";

  const applied = [...session.trajectory].reverse().find((event) => event.event === "steering.applied");
  if (!applied) return "The draft has been updated.";
  if (applied.request_text) return "Your written change request was sent to the agent.";
  switch (applied.label?.toLowerCase()) {
    case "cheaper": return "Your request: rank lower-cost options first.";
    case "more comfort": return "Your request: prioritize comfort.";
    case "explore": return "Your request: consider less obvious options.";
    case "simplify": return "Your request: prefer simpler options.";
    default: return applied.label ? `Your request: “${applied.label}”.` : "The draft has been updated.";
  }
}

export default function RevisionSummary({ session, modelEnabled }: {
  session: SteeringSession;
  modelEnabled: boolean;
}) {
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (session.revisions.length < 2) return null;

  const explain = async () => {
    if (busy || !modelEnabled) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.steeringSummary(session.id);
      setSummary(result.summary);
    } catch {
      setError("Couldn't explain this update right now. The draft and your approval controls are unchanged.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="revision-summary">
      <span className="change-chip">{changeLabel(session)}</span>
      {modelEnabled && (
        <div className="revision-summary-action">
          <button className="linkbtn" onClick={explain} disabled={busy}>
            {busy ? "Preparing explanation…" : "Explain changes"}
          </button>
          <span>Clicking shares the proposal context and both drafts with your enabled model.</span>
        </div>
      )}
      {summary && <p className="revision-summary-text" role="status">{summary}</p>}
      {error && <p className="revision-summary-error" role="alert">{error}</p>}
    </div>
  );
}
