import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { subscribeStream } from "../stream";
import type { Edge, SteeringSession } from "../types";
import AdaptiveSteer from "./AdaptiveSteer";
import ProposalBody from "./ProposalBody";
import RevisionSummary from "./RevisionSummary";

const TRAJECTORY_TEXT: Record<string, string> = {
  "steering.proposal_submitted": "Agent shared a draft",
  "steering.applied": "You asked for a change",
  "steering.proposal_revised": "Agent updated the draft",
  "steering.accepted": "You approved the draft",
  "steering.rejected": "You rejected the draft",
};

const TRAJECTORY_COLOR: Record<string, string> = {
  "steering.proposal_submitted": "var(--c-blue)",
  "steering.applied": "var(--c-orange)",
  "steering.proposal_revised": "var(--c-pink)",
  "steering.accepted": "var(--c-green)",
  "steering.rejected": "var(--red, #d70015)",
};

export default function SteeringPanel({ onEvent, onCount, modelEnabled = false, summaryEnabled = false }: {
  onEvent?: (msg: string) => void;
  onCount?: (n: number) => void;
  modelEnabled?: boolean;
  summaryEnabled?: boolean;
}) {
  const [sessions, setSessions] = useState<SteeringSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [strong, setStrong] = useState(false);
  const [msg, setMsg] = useState("");
  const [loadError, setLoadError] = useState(false);
  const touch = useRef<{ x: number; y: number } | null>(null);
  const lastHash = useRef("");
  const seenVersion = useRef<Record<string, number>>({});

  const load = useCallback(async () => {
    try {
      const list = await api.steering();
      setLoadError(false);
      // Unchanged payloads never touch state: no re-render, no list churn.
      const h = JSON.stringify(list.map((s) => [
        s.id,
        s.version,
        s.status,
        s.updated_at,
        s.pending_steer,
        s.trajectory.length,
        s.trajectory[s.trajectory.length - 1]?.event,
      ]));
      if (h === lastHash.current) return;
      lastHash.current = h;
      setSessions(list);
      onCount?.(list.length);
      setActiveId((cur) => (cur && list.some((s) => s.id === cur) ? cur : list[0]?.id ?? null));
    } catch {
      // A failed load is an error, never an empty pad.
      if (sessions.length === 0) setLoadError(true);
    }
  }, [onCount, sessions.length]);

  useEffect(() => {
    load();
    // Revisions arrive over the shared tab stream, not a poll timer.
    // A slow backup poll survives missed events; it almost never fires.
    const unsub = subscribeStream(load);
    const backup = setInterval(load, 60000);
    return () => {
      unsub();
      clearInterval(backup);
    };
  }, [load]);

  // Magnitude is per-proposal, per-moment — never sticky across sessions.
  useEffect(() => { setStrong(false); }, [activeId]);
  useEffect(() => { setMsg(""); }, [activeId]);
  const active = sessions.find((s) => s.id === activeId) ?? sessions[0] ?? null;
  const waiting = Boolean(active?.pending_steer);
  const isExample = active?.agent?.name === "switchboard_demo";
  const isSample = active?.agent?.kind === "simulation" || isExample;

  useEffect(() => {
    if (!active) return;
    const previous = seenVersion.current[active.id];
    if (previous !== undefined && active.version > previous) {
      setMsg("The agent updated the draft. Review it before approving.");
    }
    seenVersion.current[active.id] = active.version;
  }, [active?.id, active?.version]);

  const steer = async (edge: Edge | null, requestText?: string) => {
    if (!active || active.locked || waiting) return false;
    const text = requestText?.trim();
    const d = edge ? active.directions.find((x) => x.edge === edge) : null;
    if (edge && !d) return false; // never fire a direction the agent did not declare
    if (!edge && !text) return false;
    try {
      await api.steerSession(active.id, text
        ? { request_text: text }
        : { edge: edge!, magnitude: strong ? 1.75 : 0.75 });
      setMsg(text
        ? `Your request was sent to ${active.agent?.name ?? "the agent"}. Nothing has been approved.`
        : `Your change request was sent to ${active.agent?.name ?? "the agent"}. Nothing has been approved.`);
      onEvent?.(text ? "Custom change request sent." : "Change request sent.");
    } catch {
      setMsg("That change request was refused. Nothing was sent.");
      return false;
    }
    setStrong(false);
    load();
    return true;
  };

  const [resolving, setResolving] = useState<"left" | "right" | null>(null);
  const resolve = async (outcome: "accepted" | "rejected") => {
    if (!active) return;
    const dir = outcome === "accepted" ? "right" : "left";
    try {
      await api.resolveSteering(active.id, outcome);
      setMsg(outcome === "accepted"
        ? `Draft approved for ${active.agent?.name ?? "the agent"}.`
        : `Draft rejected. ${active.agent?.name ?? "The agent"} was told not to use it.`);
      onEvent?.(outcome === "accepted" ? "Proposal approved and sent." : "Proposal rejected.");
      if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        setResolving(dir);
        setTimeout(() => {
          load();
          setResolving(null);
        }, 380);
        return;
      }
    } catch {
      setMsg("That session is already closed.");
    }
    load();
  };

  const onTouchEnd = (e: React.TouchEvent) => {
    const s = touch.current;
    touch.current = null;
    if (!s || !active) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - s.x;
    const dy = t.clientY - s.y;
    const adx = Math.abs(dx);
    const ady = Math.abs(dy);
    if (Math.max(adx, ady) < 64) return;
    if (ady > adx * 1.5) return; // vertical intent is scrolling on a proposal card
    steer(dx > 0 ? "right" : "left");
  };

  const dirBtn = (edge: Edge) => {
    const d = active?.directions.find((x) => x.edge === edge);
    if (!d) return null;
    return (
      <button className={`steer-choice steer-choice-${edge}`} onClick={() => steer(edge)}
        disabled={waiting}
        aria-label={`Ask the agent: ${d.label} (${strong ? "a lot" : "a little"}). ${d.expected_effect}`}>
        <span className="steer-label">{d.label}</span>
        <span className="steer-effect">{d.expected_effect}</span>
      </button>
    );
  };

  if (!active) {
    // A failed load is an error panel, never a silent gap.
    if (!loadError) return null;
    return (
      <div className="panel steering-panel" role="alert">
        <div className="panel-head">
          <h2>Review agent proposals</h2>
          <button className="linkbtn" onClick={load}>Retry</button>
        </div>
        <div className="empty">
          Couldn't reach your proposals — a connection problem, not an empty pad.
        </div>
      </div>
    );
  }

  return (
    <div className={`panel steering-panel${resolving ? ` resolving resolving-${resolving}` : ""}`}>
      <div className="panel-head">
        <h2>Review agent proposals</h2>
        <span className="pill">{sessions.length} draft{sessions.length === 1 ? "" : "s"} to review</span>
      </div>

      {sessions.length > 1 && (
        <div className="steer-tabs" role="tablist" aria-label="Live proposals">
          {sessions.map((s) => (
            <button key={s.id} className={s.id === active.id ? "steer-tab active" : "steer-tab"}
              onClick={() => setActiveId(s.id)}>
              {s.agent?.name === "switchboard_demo" ? "Example" : s.agent?.name ?? "agent"} · {s.title}
            </button>
          ))}
        </div>
      )}
      <div className="stage-question">
        <span className="stage-eyebrow">
          {isExample ? "Example draft" : `Draft from ${active.agent?.name ?? "your agent"}`} · {active.category}
          {active.project ? ` · ${active.project}` : ""} · Current draft
          {active.locked && <span className="locked-pill">Always asks you</span>}
        </span>
        <span className="stage-q-text">{active.title}</span>
      </div>
      <div
        className="proposal-text"
        onTouchStart={(e) => { touch.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }; }}
        onTouchEnd={onTouchEnd}
      >
        <ProposalBody session={active} />
      </div>
      <RevisionSummary key={`${active.id}:${active.version}`} session={active} modelEnabled={summaryEnabled} />
      {waiting && (
        <div className="callout">
          Change request sent: “{active.pending_steer?.request_text ?? active.pending_steer?.label}”. The agent is preparing a new draft; this one is not approved.
        </div>
      )}
      {isSample && !waiting && active.revisions[active.revisions.length - 1]?.note?.startsWith("Sample agent:") && (
        <div className="callout sample-limitation">This preview only demonstrates the four listed choices, so the draft stayed the same for that request.</div>
      )}

      {active.locked ? (
        <div className="locked-box">
          This type of request always needs your direct approval. Find it in “Waiting on you” and answer it there.
        </div>
      ) : (
        <div className="steerpad" role="group" aria-label="Request a change to this draft">
          <div className="steerpad-head">
            <div className="steer-step-copy">
              <span className="steer-step">1 · Refine the draft</span>
              <span className="steerpad-title">Want the agent to change something?</span>
              <span className="steerpad-hint">Pick one request. The agent will prepare a new draft; nothing is approved yet.</span>
            </div>
          </div>
          <div className="steer-options" role="group" aria-label="Ways to change the draft">
            {dirBtn("top")}
            {dirBtn("left")}
            {dirBtn("right")}
            {dirBtn("bottom")}
          </div>
          <AdaptiveSteer key={active.id} sessionId={active.id} modelEnabled={modelEnabled}
            disabled={waiting} onSend={(text) => steer(null, text)} />
          <div className="steer-foot">
            <span className="steer-strength-label">How much should it prioritize your request?</span>
            <div className="seg seg-mini" role="group" aria-label="How much the agent should prioritize your request">
              <button className={!strong ? "tab active" : "tab"} onClick={() => setStrong(false)} aria-pressed={!strong}>A little</button>
              <button className={strong ? "tab active" : "tab"} onClick={() => setStrong(true)} aria-pressed={strong}>A lot</button>
            </div>
          </div>
        </div>
      )}

      {!active.locked && (
        <>
          <div className="steer-approval">
            <span className="steer-step">2 · Approve or reject</span>
            <p className="accept-caption">
              Approving lets {active.agent?.name ?? "the agent"} carry out this draft.
            </p>
            <div className="taprow steer-resolve">
              <button className="primary" disabled={waiting} onClick={() => resolve("accepted")}>
                {waiting ? "Waiting for the new draft…" : "Approve this draft"}
              </button>
              <button disabled={waiting} onClick={() => resolve("rejected")}>Reject proposal</button>
            </div>
          </div>
        </>
      )}
      {msg && <div className="empty" role="status">{msg}</div>}
      {active.trajectory.length > 0 && (
        <details className="trajectory">
          <summary className="trajectory-title">Change history · {active.trajectory.length} steps</summary>
          <div className="trajectory-list">
            {active.trajectory.map((t, i) => (
              <div className="trajectory-row" key={i}>
                <span className="trajectory-dot" style={{ background: TRAJECTORY_COLOR[t.event] ?? "var(--c-blue)" }} />
                <span>
                  {TRAJECTORY_TEXT[t.event] ?? t.event}
                  {t.label ? ` — ${t.label}` : ""}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
