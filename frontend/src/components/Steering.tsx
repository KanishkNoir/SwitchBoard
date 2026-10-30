import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Edge, SteeringSession } from "../types";

const ARROW: Record<Edge, string> = { top: "↑", left: "←", right: "→", bottom: "↓" };

const TRAJECTORY_TEXT: Record<string, string> = {
  "steering.proposal_submitted": "Agent submitted a proposal",
  "steering.applied": "You steered",
  "steering.proposal_revised": "Agent revised the proposal",
  "steering.accepted": "You accepted it",
  "steering.rejected": "You rejected it",
};

const TRAJECTORY_COLOR: Record<string, string> = {
  "steering.proposal_submitted": "var(--c-blue)",
  "steering.applied": "var(--c-orange)",
  "steering.proposal_revised": "var(--c-pink)",
  "steering.accepted": "var(--c-green)",
  "steering.rejected": "var(--red, #d70015)",
};

function sentences(text: string): string[] {
  return text.split(/(?<=[.!?])\s+|\n/).map((s) => s.trim()).filter(Boolean);
}

/** Current proposal with sentences that are new in this version highlighted. */
function ProposalBody({ session }: { session: SteeringSession }) {
  const revs = session.revisions;
  const prev = revs.length > 1 ? revs[revs.length - 2].proposal_text : null;
  if (!prev) return <>{session.proposal_text}</>;
  const before = new Set(sentences(prev).map((s) => s.toLowerCase()));
  return (
    <>
      {sentences(session.proposal_text).map((s, i) =>
        before.has(s.toLowerCase()) ? (
          <span key={i}>{s} </span>
        ) : (
          <mark key={i} className="rev-new">{s} </mark>
        )
      )}
    </>
  );
}

export default function SteeringPanel({ onEvent, onCount }: {
  onEvent?: (msg: string) => void;
  onCount?: (n: number) => void;
}) {
  const [sessions, setSessions] = useState<SteeringSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [strong, setStrong] = useState(false);
  const [msg, setMsg] = useState("");
  const touch = useRef<{ x: number; y: number } | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await api.steering();
      setSessions(list);
      onCount?.(list.length);
      setActiveId((cur) => (cur && list.some((s) => s.id === cur) ? cur : list[0]?.id ?? null));
    } catch {
      /* keep last state */
    }
  }, [onCount]);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000); // agent revisions land in place
    return () => clearInterval(t);
  }, [load]);

  // Magnitude is per-proposal, per-moment — never sticky across sessions.
  useEffect(() => { setStrong(false); }, [activeId]);

  const active = sessions.find((s) => s.id === activeId) ?? sessions[0] ?? null;
  const waiting = Boolean(active?.pending_steer);
  const isExample = active?.agent?.name === "switchboard_demo";

  // "v2 → v3: Cheaper applied" — from the trajectory, at Accept time.
  const changeChip = (() => {
    if (!active || active.version < 2) return null;
    const applied = [...active.trajectory].reverse().find((t) => t.event === "steering.applied");
    return applied?.label
      ? `v${active.version - 1} → v${active.version}: ${applied.label} applied`
      : `Now at v${active.version}`;
  })();

  const steer = async (edge: Edge) => {
    if (!active || active.locked) return;
    const d = active.directions.find((x) => x.edge === edge);
    if (!d) return; // never fire a direction the agent did not declare
    try {
      await api.steerSession(active.id, edge, strong ? 1.75 : 0.75);
      setMsg(`Steered ${strong ? "strongly" : "gently"}: ${d.label}. Waiting for ${active.agent?.name ?? "the agent"} to revise…`);
      onEvent?.("Steer sent. The agent will revise its proposal.");
    } catch {
      setMsg("That steer was refused. Nothing was sent.");
    }
    setStrong(false);
    load();
  };

  const [resolving, setResolving] = useState<"left" | "right" | null>(null);
  const resolve = async (outcome: "accepted" | "rejected") => {
    if (!active) return;
    const dir = outcome === "accepted" ? "right" : "left";
    try {
      await api.resolveSteering(active.id, outcome);
      setMsg(outcome === "accepted" ? `Accepted v${active.version}. The agent has the final version.` : "Rejected. The agent has been told no.");
      onEvent?.(outcome === "accepted" ? "Proposal accepted." : "Proposal rejected.");
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
    if (!d) return <div className={`steer-cell steer-${edge} steer-empty`} aria-hidden="true" />;
    return (
      <button className={`steer-cell steer-btn steer-${edge}`} onClick={() => steer(edge)}
        disabled={waiting}
        aria-label={`${d.label} (${strong ? "strong" : "gentle"}) — ${d.expected_effect}`}>
        <span className="steer-arrow" aria-hidden="true">{ARROW[edge]}</span>
        <span className="steer-label">{d.label}</span>
        <span className="steer-effect">{d.expected_effect}</span>
      </button>
    );
  };

  if (!active) {
    return (
      <div className="panel steering-panel steering-idle">
        <div className="panel-head">
          <h2>Steer an agent</h2>
          <button className="linkbtn" onClick={async () => { await api.demoSteeringProposal(); load(); }}>
            Preview with an example
          </button>
        </div>
        <div className="empty" style={{ padding: "2px 0" }}>
          No proposals to steer right now — when an agent has a proposal instead of a yes/no question, it appears here.
        </div>
      </div>
    );
  }

  return (
    <div className={`panel steering-panel${resolving ? ` resolving resolving-${resolving}` : ""}`}>
      <div className="panel-head">
        <h2>Steer an agent</h2>
        <span className="pill">{sessions.length} live proposal{sessions.length > 1 ? "s" : ""}</span>
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
          {isExample ? "Example · " : ""}{active.agent?.name ?? "Agent"} · {active.category}
          {active.project ? ` · project: ${active.project}` : ""} · version {active.version}
          {active.locked && <span className="locked-pill">Locked · deliberate tap only</span>}
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
      {waiting && (
        <div className="callout">
          You steered “{active.pending_steer?.label}” — waiting for {active.agent?.name ?? "the agent"} to revise.
        </div>
      )}
      {changeChip && !waiting && <div className="change-chip">{changeChip}</div>}

      {active.locked ? (
        <div className="locked-box">
          Locked — steering is off for this category. Only you can answer it, every time,
          in “Waiting on you” below.
        </div>
      ) : (
        <div className="steerpad" role="group" aria-label="Steer this proposal">
          <div className="steerpad-head">
            <span className="steerpad-title">Which way should it lean?</span>
            <span className="steerpad-hint">Directions are requests — the revision may land differently</span>
          </div>
          <div className="steer-cross">
            {dirBtn("top")}
            {dirBtn("left")}
            <div className="steer-cell steer-center">
              <span>{waiting ? "Waiting…" : "Steering only"}</span>
              <small>Never buys, sends or deletes</small>
            </div>
            {dirBtn("right")}
            {dirBtn("bottom")}
          </div>
          <div className="steer-foot">
            <div className="seg seg-mini" role="group" aria-label="Steer strength">
              <button className={!strong ? "tab active" : "tab"} onClick={() => setStrong(false)} aria-pressed={!strong}>Gentle</button>
              <button className={strong ? "tab active" : "tab"} onClick={() => setStrong(true)} aria-pressed={strong}>Strong</button>
            </div>
            <span className="steerpad-hint">{strong ? "Push it hard — still never approves" : "A nudge, not a shove"}</span>
          </div>
        </div>
      )}

      {!active.locked && (
        <>
          <p className="accept-caption">
            Steering changed nothing yet. Accept sends this exact v{active.version} to{" "}
            {active.agent?.name ?? "the agent"} to act on.
          </p>
          <div className="taprow steer-resolve">
            <button className="primary" disabled={waiting} onClick={() => resolve("accepted")}>
              {waiting ? "Waiting for revision…" : `Accept v${active.version}`}
            </button>
            <button onClick={() => resolve("rejected")}>Reject</button>
          </div>
        </>
      )}
      {msg && <div className="empty" role="status">{msg}</div>}
      {active.trajectory.length > 0 && (
        <div className="trajectory">
          <div className="trajectory-title">The path so far</div>
          {active.trajectory.map((t, i) => (
            <div className="trajectory-row" key={i}>
              <span className="trajectory-dot" style={{ background: TRAJECTORY_COLOR[t.event] ?? "var(--c-blue)" }} />
              <span>
                {TRAJECTORY_TEXT[t.event] ?? t.event}
                {t.label ? ` — ${t.label}` : ""}{t.version ? ` (v${t.version})` : ""}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
