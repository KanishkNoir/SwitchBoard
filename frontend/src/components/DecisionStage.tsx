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

const EDGE_LABEL: Record<Edge, string> = { top: "top", left: "left", right: "right", bottom: "bottom" };
const KEY_EDGE: Record<string, Edge> = {
  ArrowUp: "top",
  ArrowLeft: "left",
  ArrowRight: "right",
  ArrowDown: "bottom",
};

export default function DecisionStage({ payload, imageSrc, objects, busy, onSteer, activeOverlay }: Props) {
  const mediaRef = useRef<HTMLDivElement>(null);
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
    return (
      <button
        className={`edge e-${edge}`}
        disabled={!a}
        onClick={() => a && onSteer(a.action_id)}
        aria-label={a ? `${EDGE_LABEL[edge]}: ${a.label}` : edge}
      >
        <small>{EDGE_LABEL[edge]}</small>
        <span>{a ? a.label : "—"}</span>
      </button>
    );
  };

  return (
    <div className="stage">
      <div
        className="stage-media"
        ref={mediaRef}
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
            <span className="big">{busy ?? "Nothing waiting on you."}</span>
            Load a demo below, or connect an agent — when several agents ask the same
            thing, you answer it once, here.
          </div>
        )}
      </div>

      <div className="edgebar">
        {edgeBtn("top")}
        {edgeBtn("left")}
        <div className="e-q">{payload ? payload.question : "No active question"}</div>
        {edgeBtn("right")}
        {edgeBtn("bottom")}
      </div>
      <div className="question-meta">
        <b>Gestures steer the recommendation. They never authorize a purchase, send, or deletion.</b>
        {payload && <b>arrow keys / swipe work too</b>}
      </div>
    </div>
  );
}
