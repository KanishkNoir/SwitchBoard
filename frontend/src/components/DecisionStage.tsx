import { useCallback, useEffect, useRef } from "react";
import type { DecisionPayload, Edge, GroundedObject } from "../types";

interface Props {
  payload: DecisionPayload | null;
  imageSrc: string | null;
  objects: GroundedObject[];
  busy: string | null;
  onSteer: (actionId: string) => void;
  activeOverlay?: string | null;
}

const KEY_EDGE: Record<string, Edge> = {
  ArrowUp: "top",
  ArrowLeft: "left",
  ArrowRight: "right",
  ArrowDown: "bottom",
};

export default function DecisionStage({ payload, imageSrc, objects, busy, onSteer, activeOverlay }: Props) {
  const touch = useRef<{ x: number; y: number } | null>(null);

  const actionFor = useCallback(
    (edge: Edge) => payload?.actions.find((a) => a.edge === edge),
    [payload]
  );

  const steerEdge = useCallback(
    (edge: Edge) => {
      const a = actionFor(edge);
      if (a) onSteer(a.action_id);
    },
    [actionFor, onSteer]
  );

  // Keyboard steering: arrows mean the same thing as swipe/click (LLD 16.3).
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      const edge = KEY_EDGE[e.key];
      if (edge && payload) {
        e.preventDefault();
        steerEdge(edge);
      }
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [payload, steerEdge]);

  const onTouchEnd = (e: React.TouchEvent) => {
    const s = touch.current;
    touch.current = null;
    if (!s || !payload) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - s.x;
    const dy = t.clientY - s.y;
    if (Math.max(Math.abs(dx), Math.abs(dy)) < 36) return;
    steerEdge(Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : dy > 0 ? "bottom" : "top");
  };

  const edgeBtn = (edge: Edge) => {
    const a = actionFor(edge);
    if (!a) return null;
    return (
      <button
        className={`steer-choice steer-choice-${edge}`}
        onClick={() => onSteer(a.action_id)}
        aria-label={`Ask for ${a.label}: ${a.expected_effect}`}
      >
        <span className="steer-label">{a.label}</span>
        <span className="steer-effect">{a.expected_effect}</span>
      </button>
    );
  };

  return (
    <div className="stage">
      <div className="stage-question">
        <span className="stage-eyebrow">{payload ? "This demo agent is asking" : "Demo steering stage"}</span>
        <span key={payload ? payload.question : "none"} className="stage-q-text">
          {payload ? payload.question : "Which way should a suggestion lean?"}
        </span>
        <span className="stage-q-sub">
          {payload
            ? payload.context_summary ?? "Pick a direction below — the suggestion re-ranks or redraws that way."
            : "Load a demo below and steer its suggestion four ways. Real questions from your agents arrive in the inbox, where you Allow or Deny them."}
        </span>
      </div>

      <div
        className="stage-media"
        onTouchStart={(e) => {
          touch.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
        }}
        onTouchEnd={onTouchEnd}
      >
        {imageSrc ? (
          <div className="stage-frame">
            <img src={imageSrc} alt="Generated workspace scene" />
            {activeOverlay && (
              <img
                className="mask-overlay"
                src={`data:image/png;base64,${activeOverlay}`}
                alt="Segmentation mask overlay"
              />
            )}
            {objects.map((o) => (
              <div
                key={o.id + o.label}
                className="bbox"
                style={{
                  left: `${(o.bbox.x1 / o.bbox.w) * 100}%`,
                  top: `${(o.bbox.y1 / o.bbox.h) * 100}%`,
                  width: `${((o.bbox.x2 - o.bbox.x1) / o.bbox.w) * 100}%`,
                  height: `${((o.bbox.y2 - o.bbox.y1) / o.bbox.h) * 100}%`,
                }}
              >
                <span>{o.label}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="stage-empty">
            <span className="big">{busy ?? "Nothing loaded yet."}</span>
            Try <b>Trade-off demo</b> or <b>Visual demo</b> below, then choose how to ask the agent to
            change its suggestion.
          </div>
        )}
      </div>

      {payload ? (
        <div className="steerpad" role="group" aria-label="Improve this suggestion">
          <div className="steerpad-head">
            <div className="steer-step-copy">
              <span className="steer-step">Ask for a change</span>
              <span className="steerpad-title">How would you improve this suggestion?</span>
              <span className="steerpad-hint">Choose one request for a new version. This does not approve anything.</span>
            </div>
          </div>
          <div className="steer-options" role="group" aria-label="Ways to improve the suggestion">
            {edgeBtn("top")}
            {edgeBtn("left")}
            {edgeBtn("right")}
            {edgeBtn("bottom")}
          </div>
        </div>
      ) : (
        <div className="steerpad steerpad-idle">
          Load a sample suggestion to see ways you can ask the agent to change it. A change request never approves the plan.
        </div>
      )}
    </div>
  );
}
