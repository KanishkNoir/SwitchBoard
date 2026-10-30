import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Edge, SteeringSession } from "../types";
import { catColor } from "./Panels";

const ARROW: Record<Edge, string> = { top: "↑", left: "←", right: "→", bottom: "↓" };

const TRAJECTORY_TEXT: Record<string, string> = {
  "steering.proposal_submitted": "Agent submitted a proposal",
  "steering.applied": "You steered",
  "steering.proposal_revised": "Agent revised the proposal",
  "steering.accepted": "You accepted it",
  "steering.rejected": "You rejected it",
};

export default function SteeringPanel({ onEvent }: { onEvent?: (msg: string) => void }) {
  const [sessions, setSessions] = useState<SteeringSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [strong, setStrong] = useState(false);
  const [msg, setMsg] = useState("");
  const touch = useRef<{ x: number; y: number } | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await api.steering();
      setSessions(list);
      setActiveId((cur) => (cur && list.some((s) => s.id === cur) ? cur : list[0]?.id ?? null));
    } catch {
      /* keep last state */
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000); // agent revisions land in place
    return () => clearInterval(t);
  }, [load]);

  const active = sessions.find((s) => s.id === activeId) ?? sessions[0] ?? null;

  const steer = async (edge: Edge) => {
    if (!active) return;
    try {
      await api.steerSession(active.id, edge, strong ? 1.75 : 0.75);
      setMsg(`Steered: ${active.directions.find((d) => d.edge === edge)?.label}. Waiting for ${active.agent?.name ?? "the agent"} to revise…`);
      onEvent?.("Steer sent. The agent will revise its proposal.");
    } catch {
      setMsg("That steer was refused. Nothing was sent.");
    }
    load();
  };

  const resolve = async (outcome: "accepted" | "rejected") => {
    if (!active) return;
    try {
      await api.resolveSteering(active.id, outcome);
      setMsg(outcome === "accepted" ? "Accepted. The agent has the final version." : "Rejected. The agent has been told no.");
      onEvent?.(outcome === "accepted" ? "Proposal accepted." : "Proposal rejected.");
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
    if (Math.max(adx, ady) < 36) return;
    if (ady > adx * 1.5) return; // vertical intent is scrolling on a proposal card
    steer(dx > 0 ? "right" : "left");
  };

  const dirBtn = (edge: Edge) => {
    const d = active?.directions.find((x) => x.edge === edge);
    if (!d) return <div className={`steer-cell steer-${edge} steer-empty`} aria-hidden="true" />;
    return (
      <button className={`steer-cell steer-btn steer-${edge}`} onClick={() => steer(edge)}
        aria-label={`${d.label} — ${d.expected_effect}`}>
        <span className="steer-arrow" aria-hidden="true">{ARROW[edge]}</span>
        <span className="steer-label">{d.label}</span>
        <span className="steer-effect">{d.expected_effect}</span>
      </button>
    );
  };

  return (
    <div className="panel steering-panel">
      <div className="panel-head">
        <h2>Steer an agent</h2>
        <span className="pill">{sessions.length ? `${sessions.length} live proposal${sessions.length > 1 ? "s" : ""}` : "the centrepiece"}</span>
      </div>

      {!active ? (
        <div className="empty">
          When any of your agents — OpenCode, Muse, Hermes, any harness — has a
          proposal instead of a yes/no question, it lands here. You nudge it:
          cheaper, bolder, simpler. The agent revises. You accept only when it's
          right, with a separate tap. Steering never approves anything by itself.
          <div className="taprow" style={{ marginTop: 12 }}>
            <button className="primary" onClick={async () => { await api.demoSteeringProposal(); load(); }}>
              See it live — load a demo proposal
            </button>
          </div>
        </div>
      ) : (
        <>
          {sessions.length > 1 && (
            <div className="steer-tabs" role="tablist" aria-label="Live proposals">
              {sessions.map((s) => (
                <button key={s.id} className={s.id === active.id ? "steer-tab active" : "steer-tab"}
                  onClick={() => setActiveId(s.id)}>
                  {s.agent?.name ?? "agent"} · {s.title}
                </button>
              ))}
            </div>
          )}
          <div className="stage-question">
            <span className="stage-eyebrow">
              {active.agent?.name ?? "Agent"} · <span style={{ color: catColor(active.category) }}>{active.category}</span> · version {active.version}
            </span>
            <span className="stage-q-text">{active.title}</span>
          </div>
          <div
            className="proposal-text"
            onTouchStart={(e) => { touch.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }; }}
            onTouchEnd={onTouchEnd}
          >
            {active.proposal_text}
          </div>
          {active.pending_steer && (
            <div className="callout">
              You steered “{active.pending_steer.label}” — waiting for {active.agent?.name ?? "the agent"} to revise.
            </div>
          )}
          <div className="steerpad" role="group" aria-label="Steer this proposal">
            <div className="steerpad-head">
              <span className="steerpad-title">Which way should it lean?</span>
              <span className="steerpad-hint">Tap a direction · swipe the proposal left/right</span>
            </div>
            <div className="steer-cross">
              {dirBtn("top")}
              {dirBtn("left")}
              <div className="steer-cell steer-center">
                <span>Steering only</span>
                <small>Never buys, sends or deletes</small>
              </div>
              {dirBtn("right")}
              {dirBtn("bottom")}
            </div>
            <div className="steer-foot">
              <button className={strong ? "chip active" : "chip"} onClick={() => setStrong(!strong)} aria-pressed={strong}>
                {strong ? "Strong steer" : "Gentle steer"}
              </button>
              <span className="steerpad-hint">{strong ? "Push it hard in that direction" : "A nudge, not a shove"}</span>
            </div>
          </div>
          <div className="taprow steer-resolve">
            <button className="primary" onClick={() => resolve("accepted")}>Accept this version</button>
            <button onClick={() => resolve("rejected")}>Reject</button>
          </div>
          {msg && <div className="empty" role="status">{msg}</div>}
          {active.trajectory.length > 0 && (
            <div className="trajectory">
              <div className="trajectory-title">The path so far</div>
              {active.trajectory.map((t, i) => (
                <div className="trajectory-row" key={i}>
                  <span className="trajectory-dot" />
                  <span>
                    {TRAJECTORY_TEXT[t.event] ?? t.event}
                    {t.label ? ` — ${t.label}` : ""}{t.version ? ` (v${t.version})` : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
