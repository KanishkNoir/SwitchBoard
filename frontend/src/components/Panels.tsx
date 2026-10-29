import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AttentionHealth, DriftRow, GroundedObject, InboxItem, Passport } from "../types";

export function ObjectsPanel({
  objects,
  selected,
  onSelect,
}: {
  objects: GroundedObject[];
  selected?: string | null;
  onSelect?: (o: GroundedObject) => void;
}) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Grounded objects</h2>
        <span className="mono-note">SAM 3.1 evidence — not policy</span>
      </div>
      {objects.length === 0 ? (
        <div className="empty">
          No segmentation yet. Run the SAM 3.1 demo and the objects it finds will appear
          here with their boxes.
        </div>
      ) : (
        objects.map((o) => (
          <div
            className={`obj clickable${selected === o.label ? " selected" : ""}`}
            key={o.id + o.label}
            onClick={() => onSelect?.(o)}
            title={o.overlay_png_b64 ? "Click to view the mask" : "No mask decoded"}
          >
            <span className="swatch" />
            <span className="lbl">{o.label}</span>
            <span className="bb">
              box {o.bbox.x1},{o.bbox.y1} → {o.bbox.x2},{o.bbox.y2} · frame {o.bbox.w}×
              {o.bbox.h} · mask {o.mask_data_len ?? 0} chars ({o.mask_encoding ?? "unknown"})
              {o.overlay_png_b64 ? " · click for mask" : ""}
            </span>
          </div>
        ))
      )}
    </div>
  );
}

export function InboxPanel({
  items,
  onRefresh,
  onAnswered,
}: {
  items: InboxItem[];
  onRefresh: () => void;
  onAnswered?: (msg: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [remember, setRemember] = useState(true);
  const [keywords, setKeywords] = useState("");
  const [scopeKey, setScopeKey] = useState("");
  const [scopeVal, setScopeVal] = useState("");
  const [health, setHealth] = useState<AttentionHealth | null>(null);
  const [drift, setDrift] = useState<DriftRow[]>([]);
  const seenAt = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    const now = Date.now();
    for (const i of items) if (!seenAt.current.has(i.id)) seenAt.current.set(i.id, now);
    api.attentionHealth().then(setHealth).catch(() => setHealth(null));
    api.drift().then(setDrift).catch(() => setDrift([]));
  }, [items]);

  const submit = async (item: InboxItem) => {
    if (!answer.trim()) return;
    const kw = keywords.split(",").map((k) => k.trim()).filter(Boolean);
    const save_rule = remember
      ? {
          keywords: kw.length
            ? kw
            : item.question_text.toLowerCase().replace(/[^a-z0-9 ]/g, "").split(" ").filter(Boolean).slice(0, 3),
          scope: scopeKey.trim() ? { mandatory: { [scopeKey.trim()]: scopeVal.trim() } } : {},
        }
      : null;
    const out = await api.answerInbox(item.id, {
      answer: { value: answer.trim() },
      save_rule,
      dwell_ms: seenAt.current.has(item.id) ? Date.now() - seenAt.current.get(item.id)! : null,
    });
    onAnswered?.(
      out.rule
        ? `Answered and rule ${out.rule.action} — future in-scope repeats will not ask again.`
        : "Answered. Not saved as a rule."
    );
    setOpen(null);
    setAnswer("");
    setKeywords("");
    onRefresh();
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Waiting on you</h2>
        <button onClick={onRefresh}>Refresh</button>
      </div>
      {drift.some((d) => d.status === "drift_suspected") && (
        <div className="empty" style={{ borderColor: "var(--warn, #b45309)", textAlign: "left" }}>
          Silent drift suspected: a standing rule's recent outcomes turned negative, so
          Switchboard paused it (recalibration hold) instead of letting it keep answering
          from a world that may have changed. Review it under Rules, then answer a few
          fresh questions to release the hold.
        </div>
      )}
      {health && health.risk !== "ok" && health.risk !== "unknown" && (
        <div className="empty" style={{ borderColor: "var(--warn, #b45309)", textAlign: "left" }}>
          {health.risk === "elevated" ? "Rubber-stamp risk: " : "Worth a look: "}
          you may be approving without reading ({health.signals.join("; ")}). Slow down on
          costly or irreversible questions — Switchboard never blocks you, it just flags the pattern.
        </div>
      )}
      {items.length === 0 ? (
        <div className="empty">
          Queue is clear. Deferred questions from your agents will land here, batched only
          when they are the same decision.
        </div>
      ) : (
        items.map((i) => (
          <div className="item" key={i.id}>
            <span className="cat">{i.category}</span>
            <span className="pri">priority {Math.round(i.priority_score)}</span>
            <br />
            {i.question_text}
            {i.batch_id && <div className="bb">batched · {i.batch_id.slice(0, 8)} — answering covers the batch</div>}
            <div style={{ marginTop: 8 }}>
              <button onClick={() => setOpen(open === i.id ? null : i.id)}>
                {open === i.id ? "Close" : "Answer"}
              </button>
            </div>
            {open === i.id && (
              <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                <input value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="your answer" />
                <label style={{ fontSize: 13, color: "var(--dim)", display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={remember}
                    onChange={(e) => setRemember(e.target.checked)}
                    style={{ width: "auto" }}
                  />
                  Remember as a rule (human-confirmed)
                </label>
                {remember && (
                  <>
                    <input value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="rule keywords (blank = first words of question)" />
                    <div style={{ display: "flex", gap: 8 }}>
                      <input value={scopeKey} onChange={(e) => setScopeKey(e.target.value)} placeholder="scope field (e.g. env)" style={{ flex: 1 }} />
                      <input value={scopeVal} onChange={(e) => setScopeVal(e.target.value)} placeholder="scope value (e.g. staging)" style={{ flex: 1 }} />
                    </div>
                  </>
                )}
                <button className="primary" onClick={() => submit(i)}>Answer once</button>
              </div>
            )}
          </div>
        ))
      )}
      <div className="note">
        Questions are batched only when they are truly the same decision. Critical and
        locked questions are never delayed to fill a batch.
      </div>
    </div>
  );
}

export function PassportPanel() {
  const [category, setCategory] = useState("purchase");
  const [passport, setPassport] = useState<Passport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setPassport(await api.passport(category.trim() || "purchase"));
      setError(null);
    } catch {
      setError("Passport unavailable.");
    }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Autonomy passport</h2>
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <input
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
          style={{ flex: 1 }}
          aria-label="Category"
        />
        <button onClick={load}>Inspect</button>
      </div>
      {error && <div className="empty">{error}</div>}
      {!passport && !error && (
        <div className="empty">
          Pick a category to see why it is allowed to act — or why it still has to ask.
        </div>
      )}
      {passport && (
        <>
          <div style={{ marginBottom: 10 }}>
            <span className="pill">
              {passport.category} · {passport.stage}
              {passport.locked ? " · locked" : ""}
            </span>
          </div>
          <dl className="kv">
            <dt>Preference epoch</dt>
            <dd>{passport.preference_epoch}</dd>
            <dt>Risk target</dt>
            <dd>{passport.risk_target} (policy goal, not a guarantee)</dd>
            <dt>Evidence state</dt>
            <dd>{passport.evidence_state}</dd>
            <dt>Gold samples</dt>
            <dd>{passport.gold_sample_count} human-confirmed</dd>
            <dt>Policy version</dt>
            <dd>{passport.policy_version}</dd>
          </dl>
          <div className="note">
            {passport.limitations.map((l) => (
              <div key={l}>{l}</div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
