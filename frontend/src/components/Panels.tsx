import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AttentionHealth, DriftRow, GroundedObject, InboxItem, NoticeItem, Passport } from "../types";

// Categories are neutral text now. The colour spectrum belongs only to the
// four steering directions; a category must never borrow a reassuring hue.
export function catColor(_name: string): string {
  return "var(--dim)";
}

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
  const [customOpen, setCustomOpen] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);

  const toggleDetail = async (item: InboxItem) => {
    if (detailOpen === item.id) {
      setDetailOpen(null);
      return;
    }
    setDetailOpen(item.id);
    setDetail(null);
    try {
      setDetail(await api.inboxDetail(item.id));
    } catch {
      setDetail(null);
    }
  };
  // Rule/answer form state is per item — typed on one card, invisible on others.
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [keywordsMap, setKeywordsMap] = useState<Record<string, string>>({});
  const [scopeMap, setScopeMap] = useState<Record<string, { key: string; val: string }>>({});
  const answer = (id: string) => answers[id] ?? "";
  const keywords = (id: string) => keywordsMap[id] ?? "";
  const scopeOf = (id: string) => scopeMap[id] ?? { key: "", val: "" };
  // Exit choreography: the card swishes off in the direction of the verdict,
  // then the list refreshes. Reduced-motion users get an instant removal.
  const [leaving, setLeaving] = useState<{ id: string; dir: "left" | "right" } | null>(null);
  const swishOut = (item: InboxItem, value: string, done: () => void) => {
    if (leaving) {
      done();
      return;
    }
    const dir = String(value).toLowerCase() === "deny" ? "left" : "right";
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      done();
      return;
    }
    setLeaving({ id: item.id, dir });
    setTimeout(() => {
      done();
      setLeaving(null);
    }, 380);
  };
  const [swipe, setSwipe] = useState<{ id: string; dx: number }>({ id: "", dx: 0 });
  const touchX = useRef<number | null>(null);
  const touchY = useRef<number | null>(null);
  const seenAt = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    const now = Date.now();
    for (const i of items) if (!seenAt.current.has(i.id)) seenAt.current.set(i.id, now);
  }, [items]);

  const dwell = (item: InboxItem) =>
    seenAt.current.has(item.id) ? Date.now() - seenAt.current.get(item.id)! : null;

  // One tap is the whole interaction for ordinary answers. Creating a rule
  // ("Always") goes through the rule sheet: scope shown, deliberate confirm.
  const derivedKeywords = (item: InboxItem) =>
    item.question_text.toLowerCase().replace(/[^a-z0-9 ]/g, "").split(" ").filter(Boolean).slice(0, 3);

  const quick = async (item: InboxItem, value: string, origin: "tap" | "swipe" = "tap") => {
    try {
      await api.answerInbox(item.id, {
        answer: { value },
        save_rule: null,
        dwell_ms: dwell(item),
        origin,
      });
      onAnswered?.(value === "deny" ? "Denied. The agent has been told no." : "Done. The agent can carry on.");
      swishOut(item, value, onRefresh);
    } catch {
      onAnswered?.("That one needs a deliberate tap — swipe is off for it. Use the buttons.");
      onRefresh();
    }
  };

  const createRule = async (item: InboxItem) => {
    const sc = scopeOf(item.id);
    if (!sc.key.trim() || !sc.val.trim()) {
      onAnswered?.("A standing rule needs a limit — tap a limit chip or fill in both scope boxes so it can't apply everywhere.");
      return;
    }
    const kw = keywords(item.id).split(",").map((k) => k.trim()).filter(Boolean);
    try {
      const out = await api.answerInbox(item.id, {
        answer: { value: "allow" },
        save_rule: {
          keywords: kw.length ? kw : derivedKeywords(item),
          scope: { mandatory: { [sc.key.trim()]: sc.val.trim() } },
        },
        dwell_ms: dwell(item),
        origin: "rule_sheet",
      });
      onAnswered?.(
        `Rule ${out.rule?.action ?? "saved"} — it starts as a suggestion. Switchboard will still ask until the category earns more trust.`
      );
      setSheetOpen(null);
      swishOut(item, "allow", onRefresh);
    } catch {
      onAnswered?.("Switchboard refused that rule (locked or unscoped categories can't get one). Nothing was saved.");
      onRefresh();
    }
  };

  // A written answer is answer-once, always. Rules are made only in the rule
  // sheet above — never as a side effect of typing an answer.
  const submitCustom = async (item: InboxItem) => {
    const text = answer(item.id).trim();
    if (!text) return;
    await api.answerInbox(item.id, {
      answer: { value: text },
      save_rule: null,
      dwell_ms: dwell(item),
      origin: "tap",
    });
    onAnswered?.("Answered once. Use Always… if you want this to become a standing rule.");
    setCustomOpen(null);
    setAnswers((m) => ({ ...m, [item.id]: "" }));
    swishOut(item, text, onRefresh);
  };

  // Tappable limits derived from the question itself — no developer vocabulary.
  const scopeChips = (item: InboxItem): { key: string; val: string; label: string }[] => {
    const chips: { key: string; val: string; label: string }[] = [];
    if (item.agent_name) chips.push({ key: "agent", val: item.agent_name, label: `Only from ${item.agent_name}` });
    chips.push({ key: "category", val: item.category, label: `Only ${item.category}` });
    const amount = item.question_text.match(/\$([\d,]+)/);
    if (amount) chips.push({ key: "max_amount", val: amount[1].replace(/,/g, ""), label: `Only under $${amount[1]}` });
    return chips;
  };

  const itemOptions = (item: InboxItem): { id: string; label: string }[] => {
    try {
      const raw = JSON.parse(item.options_json || "[]") as Record<string, unknown>[];
      return raw
        .map((o) => ({
          id: String(o.id ?? o.value ?? o.label ?? ""),
          label: String(o.label ?? o.value ?? o.id ?? ""),
        }))
        .filter((o) => o.label);
    } catch {
      return [];
    }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Waiting on you</h2>
        <button onClick={onRefresh}>Refresh</button>
      </div>
      {items.length === 0 ? (
        <div className="empty">
          All clear. When an agent needs you, its question lands here — one tap and
          you're done.
        </div>
      ) : (
        items.map((i) => {
          const opts = itemOptions(i);
          const dx = swipe.id === i.id ? swipe.dx : 0;
          const out = leaving?.id === i.id ? leaving.dir : null;
          return (
            <div
              className={`item qcard${out ? ` leaving leaving-${out}` : ""}`}
              key={i.id}
              style={{
                transform: !out && dx ? `translateX(${dx}px)` : undefined,
                background:
                  dx > 24
                    ? `linear-gradient(90deg, color-mix(in srgb, var(--c-green) ${Math.min(22, dx / 4)}%, transparent), transparent 65%)`
                    : dx < -24
                      ? `linear-gradient(270deg, color-mix(in srgb, var(--c-pink) ${Math.min(22, -dx / 4)}%, transparent), transparent 65%)`
                      : undefined,
              }}
              onTouchStart={(e) => {
                touchX.current = e.touches[0].clientX;
                touchY.current = e.touches[0].clientY;
              }}
              onTouchMove={(e) => {
                if (touchX.current === null || !i.swipe_eligible) return;
                const ndx = e.touches[0].clientX - touchX.current;
                const ndy = touchY.current !== null ? e.touches[0].clientY - touchY.current : 0;
                // Axis-lock: vertical intent belongs to scrolling, never to a decision.
                if (Math.abs(ndy) > Math.abs(ndx) * 1.5 && Math.abs(ndy) > 12) {
                  setSwipe({ id: "", dx: 0 });
                  touchX.current = null;
                  return;
                }
                setSwipe({ id: i.id, dx: Math.max(-120, Math.min(120, ndx)) });
              }}
              onTouchEnd={() => {
                if (i.swipe_eligible) {
                  if (dx > 80) quick(i, "allow", "swipe");
                  else if (dx < -80) quick(i, "deny", "swipe");
                }
                touchX.current = null;
                touchY.current = null;
                setSwipe({ id: "", dx: 0 });
              }}
            >
              <span className="cat" style={{ color: catColor(i.category) }}>{i.category}</span>
              <span className="pri">
                {i.agent_name ?? "agent"}
                {i.reversibility && i.reversibility !== "unknown" ? ` · ${i.reversibility}` : ""}
              </span>
              <div className="qtext">{i.question_text}</div>
              {(() => {
                try {
                  const p = (JSON.parse(i.context_json || "{}") as { project?: string }).project;
                  return p ? <span className="project-chip">project: {p}</span> : null;
                } catch {
                  return null;
                }
              })()}
              {i.batch_id && <div className="bb">Same decision asked more than once — one answer covers all of them.</div>}
              {i.is_locked && (
                <div style={{ margin: "6px 0" }}>
                  <span className="locked-pill" style={{ marginLeft: 0 }}>Locked · deliberate tap only</span>
                </div>
              )}
              {opts.length > 0 ? (
                <div className="taprow">
                  {opts.map((o) => (
                    <button key={o.id} className="primary" onClick={() => quick(i, o.id)}>
                      {o.label}
                    </button>
                  ))}
                  <button onClick={() => quick(i, "deny")}>None of these</button>
                </div>
              ) : (
                <div className="taprow">
                  <button className="primary" onClick={() => quick(i, "allow")}>Allow once</button>
                  <button onClick={() => quick(i, "deny")}>Deny</button>
                  {!i.is_locked && (
                    <button onClick={() => setSheetOpen(sheetOpen === i.id ? null : i.id)}>Always…</button>
                  )}
                </div>
              )}
              {sheetOpen === i.id && (
                <div className="sheet">
                  <div className="sheet-title">Make this a standing rule?</div>
                  <p>
                    Switchboard will answer similar <b>{i.category}</b> questions
                    (“{derivedKeywords(i).join(", ")}”…) without asking — but only inside
                    the limit you set. It starts as a suggestion: Switchboard keeps
                    asking until this category earns more trust.
                  </p>
                  <input value={keywords(i.id)} onChange={(e) => setKeywordsMap((m) => ({ ...m, [i.id]: e.target.value }))} placeholder={`Rule words (blank = ${derivedKeywords(i).join(", ")})`} />
                  <div className="taprow">
                    {scopeChips(i).map((c) => (
                      <button key={c.label} className="chip" onClick={() => setScopeMap((m) => ({ ...m, [i.id]: { key: c.key, val: c.val } }))}>
                        {c.label}
                      </button>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input value={scopeOf(i.id).key} onChange={(e) => setScopeMap((m) => ({ ...m, [i.id]: { key: e.target.value, val: scopeOf(i.id).val } }))} placeholder="Only when… field" style={{ flex: 1 }} />
                    <input value={scopeOf(i.id).val} onChange={(e) => setScopeMap((m) => ({ ...m, [i.id]: { key: scopeOf(i.id).key, val: e.target.value } }))} placeholder="…equals" style={{ flex: 1 }} />
                  </div>
                  <div className="taprow">
                    <button className="primary" onClick={() => createRule(i)}>Create rule & allow</button>
                    <button onClick={() => setSheetOpen(null)}>Cancel</button>
                  </div>
                </div>
              )}
              <span style={{ display: "inline-flex", gap: 4 }}>
                <button className="linkbtn" onClick={() => toggleDetail(i)}>
                  {detailOpen === i.id ? "Hide details" : "Details"}
                </button>
                <button className="linkbtn" onClick={() => setCustomOpen(customOpen === i.id ? null : i.id)}>
                  {customOpen === i.id ? "Hide" : "Write your own answer…"}
                </button>
              </span>
              {detailOpen === i.id && (
                <div className="detailbox">
                  {detail === null ? (
                    "Loading…"
                  ) : (
                    <>
                      <div>
                        Asked by <b>{String((detail.agent as Record<string, unknown> | null)?.name ?? "unknown agent")}</b>
                        {" · "}reversibility: {i.reversibility ?? "unknown"}
                        {" · "}swipe: {i.swipe_eligible ? "allowed" : `off (${(i.eligibility_reasons ?? []).join(", ")})`}
                      </div>
                      <div>
                        Trail: {((detail.events as Record<string, unknown>[] | undefined) ?? [])
                          .map((e) => String(e.event_type))
                          .join(" → ") || "—"}
                      </div>
                      <div>
                        Correcting an answer creates a new rule version — it does not undo
                        anything the agent already did outside Switchboard.
                      </div>
                    </>
                  )}
                </div>
              )}
              {customOpen === i.id && (
                <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                  <input value={answer(i.id)} onChange={(e) => setAnswers((m) => ({ ...m, [i.id]: e.target.value }))} placeholder="Your answer (once only — no rule is saved)" />
                  <button className="primary" onClick={() => submitCustom(i)}>Send answer</button>
                </div>
              )}
              {i.swipe_eligible ? (
                <div className="swipehint">Swipe right to allow · left to deny</div>
              ) : (
                <div className="swipehint">Buttons only for this one</div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}

/** Auto-answered notices live in Debrief now — the inbox is questions only. */
export function NoticesPanel({ onAnswered }: { onAnswered?: (msg: string) => void }) {
  const [notices, setNotices] = useState<NoticeItem[]>([]);
  const load = useCallback(async () => {
    try {
      setNotices(await api.notices());
    } catch {
      setNotices([]);
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  if (notices.length === 0) return null;
  return (
    <div style={{ marginBottom: 16 }}>
      <div className="cat" style={{ color: "var(--c-blue)", fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.07em" }}>
        Switchboard answered — check if you disagree
      </div>
      {notices.map((n) => (
        <div className="item" key={n.id}>
          <span className="cat">{n.category}</span>
          <span className="pri">auto-answered · warning stage</span>
          <div className="qtext">{n.question_text}</div>
          <div className="bb">
            “Looks fine” counts as you confirming it. Veto flags the rule — it can't undo
            anything the agent already did outside Switchboard.
          </div>
          <div className="taprow">
            <button className="primary" onClick={async () => { await api.dismissNotice(n.id); load(); }}>Looks fine</button>
            <button onClick={async () => { await api.vetoNotice(n.id); onAnswered?.("Veto recorded — that counts against the rule that answered."); load(); }}>Veto</button>
          </div>
        </div>
      ))}
    </div>
  );
}

/** Drift + rubber-stamp alerts belong with the rules they describe. */
export function AttentionAlerts() {
  const [health, setHealth] = useState<AttentionHealth | null>(null);
  const [drift, setDrift] = useState<DriftRow[]>([]);
  useEffect(() => {
    api.attentionHealth().then(setHealth).catch(() => setHealth(null));
    api.drift().then(setDrift).catch(() => setDrift([]));
  }, []);
  return (
    <>
      {drift.some((d) => d.status === "drift_suspected") && (
        <div className="callout">
          Silent drift suspected: a standing rule's recent outcomes turned negative, so
          Switchboard paused it (recalibration hold) instead of letting it keep answering
          from a world that may have changed. Review it under Rules, then answer a few
          fresh questions to release the hold.
        </div>
      )}
      {health && health.risk !== "ok" && health.risk !== "unknown" && (
        <div className="callout">
          {health.risk === "elevated" ? "Rubber-stamp risk: " : "Worth a look: "}
          you may be approving without reading ({health.signals.join("; ")}). Slow down on
          costly or irreversible questions — Switchboard never blocks you, it just flags the pattern.
        </div>
      )}
    </>
  );
}

const BUCKETS: { key: string; title: string; color: string }[] = [
  { key: "answered_by_you", title: "You answered", color: "var(--c-green)" },
  { key: "auto_answered", title: "Switchboard answered", color: "var(--c-blue)" },
  { key: "denied_by_you", title: "You denied", color: "var(--c-pink)" },
];

export function DebriefPanel() {
  const [rows, setRows] = useState<import("../types").DebriefRow[]>([]);
  const load = useCallback(async () => {
    try {
      setRows(await api.debrief());
    } catch {
      setRows([]);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);
  const answerText = (r: import("../types").DebriefRow) =>
    typeof r.answer === "object" && r.answer !== null
      ? String((r.answer as { value?: string }).value ?? "")
      : String(r.answer ?? "");
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Debrief</h2>
        <button onClick={load}>Refresh</button>
      </div>
      <p className="prose" style={{ marginBottom: 12 }}>
        What happened, in the order it mattered — and why. Every entry carries its
        receipt; nothing here is rewritten after the fact.
      </p>
      <NoticesPanel />
      {rows.length === 0 && <div className="empty">No decisions yet. Your agents' questions will be explained here.</div>}
      {BUCKETS.map((b) => {
        const group = rows.filter((r) => r.bucket === b.key);
        if (!group.length) return null;
        return (
          <div key={b.key} style={{ marginBottom: 16 }}>
            <div className="cat" style={{ color: b.color, fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.07em" }}>
              {b.title}
            </div>
            {group.map((r) => (
              <div className="item" key={r.decision_id}>
                <span className="cat" style={{ color: catColor(r.category) }}>{r.category}</span>
                <span className="pri">{new Date(r.created_at).toLocaleString()}</span>
                <div className="qtext" style={{ fontSize: 15 }}>{r.question_text}</div>
                <div style={{ fontSize: 13.5, color: "var(--dim)", lineHeight: 1.5 }}>
                  {r.reason_plain}
                  {answerText(r) && (
                    <>
                      {" "}Answer: <b style={{ color: "var(--ink)" }}>{answerText(r)}</b>
                    </>
                  )}
                  {r.origin && <> · via {r.origin}</>}
                  {r.dwell_ms !== null && r.dwell_ms !== undefined && (
                    <> · {(r.dwell_ms / 1000).toFixed(1)}s on screen</>
                  )}
                </div>
                {r.receipt_id && <div className="bb">receipt {r.receipt_id.slice(0, 8)}…</div>}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

export function PassportPanel() {
  const [category, setCategory] = useState("purchase");
  const [chips, setChips] = useState<string[]>(["purchase"]);
  const [passport, setPassport] = useState<Passport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (cat?: string) => {
    try {
      setPassport(await api.passport((cat ?? category).trim() || "purchase"));
      setError(null);
    } catch {
      setError("Passport unavailable.");
    }
  }, [category]);

  // One auto-loaded home: the passport opens on the default category and
  // offers real categories as chips — nobody types a category name.
  useEffect(() => {
    load("purchase");
    api.onboarding().then((s) => {
      const cats = s.categories.map((c) => c.category);
      if (cats.length) setChips(cats);
    }).catch(() => { /* keep the default chip */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Autonomy passport</h2>
      </div>
      <div className="taprow" style={{ marginBottom: 12 }}>
        {chips.map((c) => (
          <button
            key={c}
            className={c === category ? "chip active" : "chip"}
            onClick={() => { setCategory(c); load(c); }}
          >
            {c}
          </button>
        ))}
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
            {passport.risk_gate && (
              <>
                <dt>Risk gate (shadow)</dt>
                <dd>
                  {passport.risk_gate.gate_state}
                  {passport.risk_gate.wilson_upper !== null &&
                    ` · upper bound ${(passport.risk_gate.wilson_upper * 100).toFixed(1)}%`}
                  {passport.risk_gate.labels_needed > 0 &&
                    ` · ${passport.risk_gate.labels_needed} more human labels before enforcement can be considered`}
                  {" "}· measuring only, never blocks
                </dd>
              </>
            )}
            {passport.taste && passport.taste.length > 0 && (
              <>
                <dt>How you steer</dt>
                <dd>
                  {passport.taste.map(([label, n]) => `${label} ×${n}`).join(" · ")}
                  {" "}— your leans here, mirrored back; never a rule.
                </dd>
              </>
            )}
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
