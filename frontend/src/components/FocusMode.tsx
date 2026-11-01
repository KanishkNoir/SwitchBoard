import { useCallback, useEffect, useMemo, useRef, useState, type TouchEvent } from "react";
import { api } from "../api";
import { subscribeStream } from "../stream";
import type { Edge, InboxItem, SteeringSession } from "../types";

type Lane = "questions" | "proposals";

function optionsFor(item: InboxItem): { id: string; label: string }[] {
  try {
    const raw = JSON.parse(item.options_json || "[]") as Record<string, unknown>[];
    return raw.map((option) => ({
      id: String(option.id ?? option.value ?? option.label ?? ""),
      label: String(option.label ?? option.value ?? option.id ?? ""),
    })).filter((option) => option.label);
  } catch {
    return [];
  }
}

function projectFor(item: InboxItem): string | null {
  try {
    return (JSON.parse(item.context_json || "{}") as { project?: string }).project ?? null;
  } catch {
    return null;
  }
}

function directionsFor(session: SteeringSession): SteeringSession["directions"] {
  return session.directions ?? [];
}

export default function FocusMode({
  items,
  onRefresh,
  onExit,
  onAnswered,
}: {
  items: InboxItem[];
  onRefresh: () => Promise<void>;
  onExit: () => void;
  onAnswered?: (message: string) => void;
}) {
  const [lane, setLane] = useState<Lane>(items.length > 0 ? "questions" : "proposals");
  const [handled, setHandled] = useState<Set<string>>(() => new Set());
  const [deferred, setDeferred] = useState<Set<string>>(() => new Set());
  const [reviewingDeferred, setReviewingDeferred] = useState(false);
  const [passedOver, setPassedOver] = useState<Set<string>>(() => new Set());
  const [showDetails, setShowDetails] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [sessions, setSessions] = useState<SteeringSession[]>([]);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [sessionLoadError, setSessionLoadError] = useState(false);
  const [steeringBusy, setSteeringBusy] = useState(false);
  const [touchStart, setTouchStart] = useState<{ x: number; y: number } | null>(null);
  const [drag, setDrag] = useState<{ id: string; dx: number } | null>(null);
  const cardStartedAt = useRef(Date.now());

  const loadSessions = useCallback(async () => {
    try {
      const open = await api.steering();
      setSessions(open.filter((session) => session.status === "open"));
      setSessionLoadError(false);
      setSessionsLoaded(true);
    } catch {
      setMessage("Couldn't refresh proposals. Your pending work is still on the server.");
      setSessionLoadError(true);
      setSessionsLoaded(true);
    }
  }, []);

  useEffect(() => {
    void loadSessions();
    const unsubscribe = subscribeStream(() => { void loadSessions(); });
    const backup = window.setInterval(() => { void loadSessions(); }, 20000);
    return () => {
      unsubscribe();
      window.clearInterval(backup);
    };
  }, [loadSessions]);

  const unanswered = useMemo(
    () => items.filter((item) => !handled.has(item.id) && (reviewingDeferred
      ? deferred.has(item.id) && !passedOver.has(item.id)
      : !deferred.has(item.id))),
    [deferred, handled, items, passedOver, reviewingDeferred],
  );
  const activeQuestion = unanswered[0] ?? null;
  const activeProposal = sessions[0] ?? null;
  const questionTotal = handled.size + deferred.size + unanswered.length;
  const questionProgress = Math.min(questionTotal, handled.size + deferred.size + (activeQuestion ? 1 : 0));

  useEffect(() => { cardStartedAt.current = Date.now(); }, [activeQuestion?.id, activeProposal?.id]);

  const answer = async (item: InboxItem, value: string, origin: "tap" | "swipe" = "tap") => {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      await api.answerInbox(item.id, {
        answer: { value },
        save_rule: null,
        dwell_ms: Date.now() - cardStartedAt.current,
        origin,
      });
      setHandled((current) => new Set(current).add(item.id));
      setDeferred((current) => new Set([...current].filter((id) => id !== item.id)));
      setPassedOver((current) => new Set([...current].filter((id) => id !== item.id)));
      setMessage(value === "deny" ? "Denied. The agent has been told no." : "Answered once. No standing rule was saved.");
      onAnswered?.(value === "deny" ? "Denied. The agent has been told no." : "Done. The agent can carry on.");
      await onRefresh();
    } catch {
      setMessage("That answer wasn't accepted. The question is still waiting.");
      await onRefresh();
    } finally {
      setBusy(false);
    }
  };

  const deferQuestion = (item: InboxItem) => {
    if (reviewingDeferred) setPassedOver((current) => new Set(current).add(item.id));
    else setDeferred((current) => new Set(current).add(item.id));
    setMessage("Left in your inbox for later.");
  };

  const steer = async (session: SteeringSession, edge: Edge) => {
    if (steeringBusy || session.locked || session.pending_steer) return;
    const direction = directionsFor(session).find((candidate) => candidate.edge === edge);
    if (!direction) return;
    setSteeringBusy(true);
    setMessage("");
    try {
      await api.steerSession(session.id, edge, 0.75);
      setMessage(`Steered gently: ${direction.label}. Waiting for ${session.agent?.name ?? "the agent"} to revise.`);
      await loadSessions();
    } catch {
      setMessage("That steer was refused. Nothing was sent.");
    } finally {
      setSteeringBusy(false);
    }
  };

  const resolve = async (session: SteeringSession, outcome: "accepted" | "rejected") => {
    if (steeringBusy || (outcome === "accepted" && session.pending_steer)) return;
    setSteeringBusy(true);
    setMessage("");
    try {
      await api.resolveSteering(session.id, outcome);
      setMessage(outcome === "accepted"
        ? `Accepted version ${session.version}. The agent has the final version.`
        : "Rejected. The agent has been told no.");
      await loadSessions();
    } catch {
      setMessage("That proposal could not be resolved. Refresh and try again.");
    } finally {
      setSteeringBusy(false);
    }
  };

  const swipeQuestion = (event: TouchEvent<HTMLElement>, item: InboxItem) => {
    const start = touchStart;
    setTouchStart(null);
    setDrag(null);
    if (!start) return;
    if ((event.target as HTMLElement).closest("button, a, input, textarea, select")) return;
    const touch = event.changedTouches[0];
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    if (!item.swipe_eligible || item.is_locked || optionsFor(item).length > 0 || Math.abs(dx) < 82 || Math.abs(dy) > Math.abs(dx) * 1.5) return;
    void answer(item, dx > 0 ? "allow" : "deny", "swipe");
  };

  const swipeProposal = (event: TouchEvent<HTMLElement>, session: SteeringSession) => {
    const start = touchStart;
    setTouchStart(null);
    setDrag(null);
    if (!start) return;
    if ((event.target as HTMLElement).closest("button, a, input, textarea, select")) return;
    const touch = event.changedTouches[0];
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    if (Math.abs(dx) < 82 || Math.abs(dy) > Math.abs(dx) * 1.5 || session.locked || session.pending_steer) return;
    void steer(session, dx > 0 ? "right" : "left");
  };

  const proposalsUnavailable = sessionsLoaded && !sessionLoadError && sessions.length === 0;
  const questionDragX = activeQuestion && drag && drag.id === activeQuestion.id ? drag.dx : 0;
  const proposalDragX = activeProposal && drag && drag.id === activeProposal.id ? drag.dx : 0;

  return (
    <main className="focus-shell view-morph">
      <section className="focus-panel panel" aria-label="Focus mode">
        <div className="focus-heading">
          <div>
            <span className="focus-kicker">FOCUS MODE</span>
            <h2>One decision at a time</h2>
            <p>Keep the context. Move at your pace.</p>
          </div>
          <button onClick={onExit}>Exit focus</button>
        </div>

        <div className="focus-lanes" role="tablist" aria-label="Focus queue">
          <button className={lane === "questions" ? "active" : ""} role="tab" aria-selected={lane === "questions"}
            onClick={() => setLane("questions")}>
            Questions <span>{items.length}</span>
          </button>
          <button className={lane === "proposals" ? "active" : ""} role="tab" aria-selected={lane === "proposals"}
            onClick={() => setLane("proposals")}>
            Proposals <span>{sessions.length}</span>
          </button>
        </div>

        {lane === "questions" && activeQuestion && (
          <>
            <div className="focus-progress" aria-live="polite">
              <span>{reviewingDeferred ? "Reviewing later questions" : `Question ${questionProgress} of ${questionTotal}`}</span>
              <span>{handled.size} answered · {deferred.size} later</span>
              {reviewingDeferred && <button className="linkbtn" onClick={() => { setReviewingDeferred(false); setPassedOver(new Set()); }}>Back to active questions</button>}
            </div>
            <article key={activeQuestion.id} className="focus-card" style={{
              transform: questionDragX ? `translateX(${questionDragX}px) rotate(${questionDragX * 0.018}deg)` : undefined,
              transition: drag?.id === activeQuestion.id ? "none" : undefined,
              background: questionDragX > 24
                ? `linear-gradient(90deg, color-mix(in srgb, var(--c-green) ${Math.min(20, questionDragX / 5)}%, var(--panel)), var(--panel) 72%)`
                : questionDragX < -24
                  ? `linear-gradient(270deg, color-mix(in srgb, var(--c-pink) ${Math.min(20, -questionDragX / 5)}%, var(--panel)), var(--panel) 72%)`
                  : undefined,
            }} onTouchStart={(event) => {
              if (!activeQuestion.swipe_eligible || activeQuestion.is_locked || optionsFor(activeQuestion).length > 0 || (event.target as HTMLElement).closest("button, a, input, textarea, select")) return;
              setTouchStart({ x: event.touches[0].clientX, y: event.touches[0].clientY });
            }} onTouchMove={(event) => {
              if (!touchStart || !activeQuestion.swipe_eligible) return;
              const dx = event.touches[0].clientX - touchStart.x;
              const dy = event.touches[0].clientY - touchStart.y;
              if (Math.abs(dy) > Math.abs(dx) * 1.5 && Math.abs(dy) > 12) { setTouchStart(null); setDrag(null); return; }
              setDrag({ id: activeQuestion.id, dx: Math.max(-150, Math.min(150, dx)) });
            }}
              onTouchEnd={(event) => swipeQuestion(event, activeQuestion)}>
              <div className="focus-card-meta">
                <span className="cat">{activeQuestion.category}</span>
                <span>{activeQuestion.agent_name ?? "Agent"}</span>
                {projectFor(activeQuestion) && <span className="project-chip">{projectFor(activeQuestion)}</span>}
                {activeQuestion.reversibility && activeQuestion.reversibility !== "unknown" && <span>{activeQuestion.reversibility}</span>}
              </div>
              {activeQuestion.is_locked && <div className="locked-pill">Locked · deliberate tap only</div>}
              <h3>{activeQuestion.question_text}</h3>
              {activeQuestion.batch_id && <p className="focus-batch">One answer covers matching questions from more than one agent.</p>}
              <button className="linkbtn focus-details-toggle" onClick={() => setShowDetails((open) => !open)}>
                {showDetails ? "Hide context" : "Why this is here"}
              </button>
              {showDetails && (
                <div className="detailbox">
                  {activeQuestion.deadline_at && <div>Deadline: {new Date(activeQuestion.deadline_at).toLocaleString()}</div>}
                  <div>Swipe: {activeQuestion.swipe_eligible && !activeQuestion.is_locked ? "available for a simple answer" : "off for this question"}</div>
                  {(activeQuestion.eligibility_reasons ?? []).length > 0 && <div>Why it needs you: {activeQuestion.eligibility_reasons?.join(", ")}</div>}
                  {activeQuestion.context_json && <div>Context: {activeQuestion.context_json}</div>}
                </div>
              )}
              <div className="focus-actions">
                {optionsFor(activeQuestion).length > 0 ? (
                  <>
                    {optionsFor(activeQuestion).map((option) => (
                      <button key={option.id} className="primary" disabled={busy} onClick={() => void answer(activeQuestion, option.id)}>{option.label}</button>
                    ))}
                    <button disabled={busy} onClick={() => void answer(activeQuestion, "deny")}>None of these</button>
                  </>
                ) : (
                  <>
                    <button className="primary" disabled={busy} onClick={() => void answer(activeQuestion, "allow")}>Allow once</button>
                    <button disabled={busy} onClick={() => void answer(activeQuestion, "deny")}>Deny</button>
                  </>
                )}
                <button className="focus-later" onClick={() => deferQuestion(activeQuestion)}>Later</button>
              </div>
              {activeQuestion.swipe_eligible && !activeQuestion.is_locked && optionsFor(activeQuestion).length === 0 && (
                <p className="focus-gesture-hint">Swipe right to allow once · swipe left to deny. Buttons always work too.</p>
              )}
            </article>
          </>
        )}

        {lane === "questions" && !activeQuestion && (
          <div className="focus-empty">
            <span className="focus-kicker">QUESTIONS</span>
            <h3>{items.length === 0 ? "You're all caught up." : "No more questions in this pass."}</h3>
            <p>{handled.size} answered · {deferred.size} left in the inbox for later.</p>
            <div className="focus-actions">
              {deferred.size > 0 && !reviewingDeferred && <button className="primary" onClick={() => { setReviewingDeferred(true); setPassedOver(new Set()); }}>Review later questions</button>}
              {reviewingDeferred && <button className="primary" onClick={() => { setReviewingDeferred(false); setPassedOver(new Set()); }}>Back to active questions</button>}
              {!proposalsUnavailable && <button onClick={() => setLane("proposals")}>Review proposals</button>}
              <button onClick={onExit}>Return to the desk</button>
            </div>
          </div>
        )}

        {lane === "proposals" && activeProposal && (
          <>
            <div className="focus-progress" aria-live="polite">
              <span>{sessions.length} proposal{sessions.length === 1 ? "" : "s"} to review</span>
              <span>Steering never approves an action.</span>
            </div>
            <article key={activeProposal.id} className="focus-card proposal-focus-card" style={{
              transform: proposalDragX ? `translateX(${proposalDragX}px) rotate(${proposalDragX * 0.018}deg)` : undefined,
              transition: drag?.id === activeProposal.id ? "none" : undefined,
              background: proposalDragX ? `linear-gradient(${proposalDragX > 0 ? "90deg" : "270deg"}, color-mix(in srgb, var(--blue) ${Math.min(15, Math.abs(proposalDragX) / 8)}%, var(--panel)), var(--panel) 72%)` : undefined,
            }}
              onTouchStart={(event) => {
                if (activeProposal.pending_steer || activeProposal.locked || (event.target as HTMLElement).closest("button, a, input, textarea, select")) return;
                setTouchStart({ x: event.touches[0].clientX, y: event.touches[0].clientY });
              }}
              onTouchMove={(event) => {
                if (!touchStart || activeProposal.pending_steer) return;
                const dx = event.touches[0].clientX - touchStart.x;
                const dy = event.touches[0].clientY - touchStart.y;
                if (Math.abs(dy) > Math.abs(dx) * 1.5 && Math.abs(dy) > 12) { setTouchStart(null); setDrag(null); return; }
                setDrag({ id: activeProposal.id, dx: Math.max(-150, Math.min(150, dx)) });
              }}
              onTouchEnd={(event) => swipeProposal(event, activeProposal)}>
              <div className="focus-card-meta">
                <span className="cat">{activeProposal.category}</span>
                <span>{activeProposal.agent?.name ?? "Agent"}</span>
                {activeProposal.project && <span className="project-chip">{activeProposal.project}</span>}
                <span>Version {activeProposal.version}</span>
              </div>
              <h3>{activeProposal.title}</h3>
              <pre className="focus-proposal-text">{activeProposal.proposal_text}</pre>
              {activeProposal.pending_steer && <div className="callout">Steer sent: “{activeProposal.pending_steer.label}”. Waiting for a revision.</div>}
              {activeProposal.locked ? (
                <div className="locked-box">This category is locked. Proposals here cannot be steered or accepted.</div>
              ) : (
                <>
                  <div className="focus-directions" aria-label="Steering directions">
                    {directionsFor(activeProposal).map((direction) => (
                      <button key={direction.edge} disabled={steeringBusy || Boolean(activeProposal.pending_steer)}
                        onClick={() => void steer(activeProposal, direction.edge)}>
                        <span>{direction.label}</span><small>{direction.expected_effect}</small>
                      </button>
                    ))}
                  </div>
                  <p className="focus-gesture-hint">A swipe can request a left/right revision. Acceptance is always a separate tap.</p>
                  <div className="focus-actions">
                    <button className="primary" disabled={steeringBusy || Boolean(activeProposal.pending_steer)}
                      onClick={() => void resolve(activeProposal, "accepted")}>Accept version {activeProposal.version}</button>
                    <button disabled={steeringBusy} onClick={() => void resolve(activeProposal, "rejected")}>Reject</button>
                  </div>
                </>
              )}
            </article>
          </>
        )}

        {lane === "proposals" && !sessionsLoaded && (
          <div className="focus-empty" role="status">Loading proposals…</div>
        )}

        {lane === "proposals" && sessionsLoaded && sessionLoadError && (
          <div className="focus-empty" role="alert">
            <span className="focus-kicker">PROPOSALS</span>
            <h3>Couldn't load proposals.</h3>
            <p>Your pending proposals remain on the server.</p>
            <div className="focus-actions">
              <button className="primary" onClick={() => { setMessage(""); void loadSessions(); }}>Retry</button>
              {items.length > 0 && <button onClick={() => setLane("questions")}>Return to questions</button>}
            </div>
          </div>
        )}

        {lane === "proposals" && !activeProposal && !sessionLoadError && (
          <div className="focus-empty">
            <span className="focus-kicker">PROPOSALS</span>
            <h3>{items.length > 0 ? "No proposals are waiting." : "Focus session complete."}</h3>
            <p>{items.length > 0 ? "Your questions remain available in the other lane." : "No unanswered questions or open proposals remain."}</p>
            <div className="focus-actions">
              {items.length > 0 && <button className="primary" onClick={() => setLane("questions")}>Return to questions</button>}
              <button onClick={onExit}>Return to the desk</button>
            </div>
          </div>
        )}

        {message && <div className="focus-message" role="status" aria-live="polite">{message}</div>}
      </section>
    </main>
  );
}
