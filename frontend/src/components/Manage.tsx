import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AgentRow, BlastItem, RuleRow, RuleUpdate, ScopeContract } from "../types";
import { ScopeEditor, scopeDraft, scopeValue } from "./ScopeEditor";
import type { ScopeDraft } from "./ScopeEditor";

export function AgentsPanel({ readOnly = false }: { readOnly?: boolean }) {
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [name, setName] = useState("");
  const [filter, setFilter] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setAgents(await api.agents());
    } catch {
      setError("Agent list unavailable.");
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const register = async () => {
    if (!name.trim()) return;
    try {
      const out = await api.registerAgent(name.trim(), "cli");
      setNewKey(out.api_key);
      setName("");
      load();
    } catch {
      setError("Registration failed.");
    }
  };

  const visibleAgents = agents.filter((a) =>
    `${a.name} ${a.kind} ${a.id}`.toLowerCase().includes(filter.trim().toLowerCase())
  );

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Compatible agents</h2>
        <span className="agent-count">{agents.length} registered</span>
        <button onClick={load}>Refresh</button>
      </div>
      {error && <div className="empty">{error}</div>}
      {agents.length === 0 && !error && (
        <div className="empty">No agents registered. An agent key identifies a caller — it never grants rule-writing rights.</div>
      )}
      {agents.length > 0 && (
        <label className="agent-filter">
          <span>Find an agent</span>
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Name, kind, or ID" />
        </label>
      )}
      {agents.length > 0 && visibleAgents.length === 0 && (
        <div className="empty">No registered agents match “{filter}”.</div>
      )}
      {visibleAgents.map((a) => (
        <div className="item" key={a.id}>
          <span className="cat">{a.kind}</span>
          <span className="pri">{a.enabled ? "enabled" : "disabled"}</span>
          <br />
          {a.name}
          <div className="bb">id {a.id.slice(0, 8)}… · scopes {a.scopes_json}</div>
        </div>
      ))}
      {readOnly ? <p className="note">These are scripted sample agents in your disposable playground. Connect real assistants in your own Switchboard installation.</p> : <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && register()}
          placeholder="new agent name"
          style={{ flex: 1 }}
        />
        <button className="primary" onClick={register}>Register</button>
      </div>}
      {newKey && (
        <div className="note">
          New agent key (shown once — store it in that agent's env as SWITCHBOARD_AGENT_KEY):
          <pre className="out" style={{ marginTop: 8 }}>{newKey}</pre>
        </div>
      )}
    </div>
  );
}

export function RulesPanel() {
  const [rules, setRules] = useState<RuleRow[]>([]);
  const [blast, setBlast] = useState<{ ruleId: string; items: BlastItem[]; caveat?: string } | null>(null);
  const [msg, setMsg] = useState("");
  // create form
  const [cat, setCat] = useState("purchase");
  const [keywords, setKeywords] = useState("");
  const [answer, setAnswer] = useState("");
  const [scope, setScope] = useState<ScopeDraft>({ global: false, fields: [{ name: "", values: [""] }] });
  const [contract, setContract] = useState<ScopeContract | null>(null);
  const [requiredFields, setRequiredFields] = useState("");
  const [evidenceFields, setEvidenceFields] = useState("");
  const [allowGlobal, setAllowGlobal] = useState(false);
  const [contractReady, setContractReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const editRequest = useRef(0);
  // supersede form (per selected rule)
  const [sel, setSel] = useState<string | null>(null);
  const [newAnswer, setNewAnswer] = useState("");
  const [newScope, setNewScope] = useState<ScopeDraft>({ global: false, fields: [] });
  const [editContract, setEditContract] = useState<ScopeContract | null>(null);
  const [reviewHold, setReviewHold] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ ruleId: string; affected: number; plan: RuleUpdate; body: unknown } | null>(null);

  const correctionBody = (r: RuleRow) => {
    const old = JSON.parse(r.answer_json) as { value?: unknown };
    // Preserve option IDs and structured values when the answer itself is unchanged.
    return { answer: String(old.value ?? "") === newAnswer ? old : { value: newAnswer.trim() }, scope: scopeValue(newScope), expected_version_id: r.version_id };
  };

  const beginCorrection = async (r: RuleRow) => {
    const request = ++editRequest.current;
    setPreview(null);
    setEditContract(null);
    setNewAnswer("");
    setSel(null);
    try {
      const current = await api.scopeContract(r.category);
      if (request !== editRequest.current) return;
      setEditContract(current);
      setNewScope(scopeDraft(JSON.parse(r.scope_json)));
      setNewAnswer(String((JSON.parse(r.answer_json) as { value?: unknown }).value ?? ""));
      setSel(r.rule_id);
    } catch { setMsg("Could not load this category's boundaries. Try again."); }
  };

  useEffect(() => {
    let active = true;
    setContractReady(false);
    setContract(null);
    api.scopeContract(cat.trim() || "purchase").then((current) => {
      if (!active) return;
      setContract(current);
      setRequiredFields(current.required_fields.join(", "));
      setEvidenceFields(current.configured ? current.evidence_fields.join(", ") : "");
      setAllowGlobal(current.allow_global);
      setContractReady(true);
    }).catch(() => { if (active) setMsg("Category boundaries could not be loaded."); });
    return () => { active = false; };
  }, [cat]);

  const saveContract = async () => {
    if (saving) return;
    setSaving(true);
    const fields = (text: string) => text.split(",").map((v) => v.trim()).filter(Boolean);
    try {
      const out = await api.saveScopeContract(cat.trim() || "purchase", {
        required_fields: fields(requiredFields), evidence_fields: fields(evidenceFields), allow_global: allowGlobal,
      });
      setContract(out);
      editRequest.current++;
      setEditContract(null);
      setSel(null);
      setPreview(null);
      const count = out.existing_rule_violations?.length ?? 0;
      setMsg(`Boundaries saved. ${count} existing rule(s) need repair before they can answer automatically.`);
      await load();
    } catch (error) { setMsg(error instanceof Error ? error.message : "Could not save category boundaries."); }
    finally { setSaving(false); }
  };

  const previewCorrection = async (r: RuleRow) => {
    if (!newAnswer.trim()) {
      setMsg("Type the corrected answer first — then preview what it touches.");
      return;
    }
    try {
      const body = correctionBody(r);
      const out = await api.previewRule(r.rule_id, body);
      const items = out.blast_radius.affected;
      const affected = items.filter((i) => ["revalidate", "review_completed", "review_failed"].includes(i.proposed_status)).length;
      setPreview({ ruleId: r.rule_id, affected, plan: out, body });
      setBlast({ ruleId: r.rule_id, items, caveat: out.blast_radius.coverage_caveat });
    } catch (error) { setPreview(null); setMsg(error instanceof Error ? error.message : "Could not preview the correction."); }
  };

  const load = useCallback(async () => {
    try {
      setRules(await api.rules());
    } catch {
      setMsg("Rule list unavailable.");
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const create = async () => {
    if (saving) return;
    const kw = keywords.split(",").map((k) => k.trim()).filter(Boolean);
    if (!kw.length || !answer.trim()) {
      setMsg("Keywords and an answer are required.");
      return;
    }
    setSaving(true);
    try {
      await api.createRule({
        category: cat.trim() || "purchase",
        predicate: { keywords: kw },
        answer: { value: answer.trim() },
        scope: scopeValue(scope),
      });
    } catch (error) {
      setMsg(error instanceof Error ? error.message : "Could not create the rule.");
      return;
    } finally { setSaving(false); }
    setMsg(`Rule created in ${cat}. Its category's current review setting still applies.`);
    setKeywords("");
    setAnswer("");
    load();
  };

  const supersede = async (r: RuleRow) => {
    if (saving) return;
    if (!newAnswer.trim()) {
      setMsg("Type the corrected answer first.");
      return;
    }
    if (preview?.ruleId !== r.rule_id) return;
    setSaving(true);
    try {
      const out = await api.supersede(r.rule_id, preview.body);
      setPreview(null);
      setBlast({ ruleId: r.rule_id, items: out.blast_radius.affected, caveat: out.blast_radius.coverage_caveat });
      setMsg(!out.changed ? "Rule unchanged. Its version and calibration were kept." : out.required_confirmations
        ? `Rule corrected. Only this rule is paused until ${out.required_confirmations} fresh confirmation(s).`
        : "Boundary narrowed. The remaining scope keeps its calibration.");
      setSel(null);
      setNewAnswer("");
      load();
    } catch (error) { setPreview(null); setMsg(error instanceof Error ? error.message : "Could not save the correction."); }
    finally { setSaving(false); }
  };

  const showBlast = async (r: RuleRow) => {
    const out = await api.blast(r.rule_id);
    setBlast({ ruleId: r.rule_id, items: out.affected, caveat: out.coverage_caveat });
  };

  const revalidate = async (decisionId: string) => {
    const out = await api.revalidate(decisionId);
    setMsg(`Revalidated → ${out.decision}${out.answer?.value ? ` (${out.answer.value})` : ""}: ${out.reason_code}`);
  };

  const resume = async (r: RuleRow) => {
    if (saving) return;
    setSaving(true);
    try {
      await api.reviewRuleHold(r.rule_id, r.version_id);
      setReviewHold(null);
      setMsg("This rule's hold was released by your review. Other holds, hard locks and the category's review setting still apply.");
      await load();
    } catch (error) { setMsg(error instanceof Error ? error.message : "Could not review this rule."); }
    finally { setSaving(false); }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Rules &amp; corrections</h2>
        <button onClick={load}>Refresh</button>
      </div>
      {rules.length === 0 && (
        <div className="empty">No rules yet. Create one below, or answer an inbox question and choose “Always…”.</div>
      )}
      {rules.map((r) => {
        const pred = JSON.parse(r.predicate_json) as { keywords?: string[] };
        const ans = JSON.parse(r.answer_json) as { value?: string };
        const scp = JSON.parse(r.scope_json) as { mandatory?: Record<string, unknown> };
        return (
          <div className="item" key={r.rule_id}>
            <span className="cat">{r.category}</span>
            <span className="pri">v{r.version_number} · {r.source_type}</span>
            <br />
            When asked about <b>{(pred.keywords ?? []).join(", ") || "—"}</b> → <b>{ans.value ?? "—"}</b>
            <div className="bb">
              scope {scp.mandatory ? JSON.stringify(scp.mandatory) : "any"} ·{" "}
              {r.source_type === "synthetic" ? "example saved choice" : r.confirmed_by_human ? "human-confirmed" : "unconfirmed"}
            </div>
            {r.scope_validation && !r.scope_validation.valid && <div className="note">
              Automatic reuse paused: {r.scope_validation.missing_fields.length
                ? `add boundaries for ${r.scope_validation.missing_fields.join(", ")}.`
                : "this scope does not meet the category's requirements."}
            </div>}
            {r.recalibration && <div className="note">
              This rule is recalibrating: {r.recalibration.fresh_confirmations} / {r.recalibration.required_confirmations} fresh contexts confirmed.
              {r.scope_validation?.valid && <div style={{ marginTop: 6 }}><button onClick={() => setReviewHold(reviewHold === r.rule_id ? null : r.rule_id)}>Review recalibration</button></div>}
            </div>}
            {reviewHold === r.rule_id && r.recalibration && <div className="detailbox">
              <p>Confirm that <b>{ans.value ?? "this answer"}</b> is your standing choice inside the boundaries shown above. This resumes only this rule; it does not add correctness evidence.</p>
              <div className="taprow"><button className="primary" disabled={saving} onClick={() => resume(r)}>Confirm boundaries &amp; resume</button>
                <button onClick={() => setReviewHold(null)}>Keep reviewing</button></div>
            </div>}
            <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              <button onClick={() => { if (sel === r.rule_id) { setSel(null); setPreview(null); } else { void beginCorrection(r); } }}>
                Correct this rule
              </button>
              <button onClick={() => showBlast(r)}>Blast radius</button>
            </div>
            {sel === r.rule_id && (
              <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                <div className="bb">
                  Current answer: <b>{ans.value ?? "—"}</b> (v{r.version_number}) · scope{" "}
                  {scp.mandatory ? JSON.stringify(scp.mandatory) : "any"}
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    value={newAnswer}
                    onChange={(e) => { setNewAnswer(e.target.value); setPreview(null); }}
                    placeholder="corrected answer"
                    style={{ flex: 1 }}
                  />
                  <button onClick={() => previewCorrection(r)}>Preview impact</button>
                </div>
                <ScopeEditor value={newScope} onChange={(next) => { setNewScope(next); setPreview(null); }}
                  allowGlobal={editContract?.allow_global} required={editContract?.required_fields} />
                {preview?.ruleId === r.rule_id && (
                  <div className="detailbox">
                    <div>
                      {!preview.plan.changed ? "This is unchanged. The current version and any existing hold will be kept."
                        : <>This creates v{preview.plan.version_number}. {preview.plan.required_confirmations
                          ? `Only this rule pauses until ${preview.plan.required_confirmations} fresh confirmation(s).`
                          : "The remaining, narrower scope keeps its calibration."} The old version stays in the ledger.</>}
                      {" "}<b>{preview.affected}</b> recorded work item(s) need review under the proposed rule. Unknown coverage is listed separately below.
                    </div>
                    <div className="taprow">
                      <button className="primary" disabled={saving} onClick={() => supersede(r)}>Confirm correction</button>
                      <button onClick={() => setPreview(null)}>Keep current rule</button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      {blast && (
        <div style={{ marginTop: 14 }}>
          <h2>Blast radius</h2>
          {blast.items.length === 0 && <div className="empty">No recorded decisions used this rule version.</div>}
          {blast.items.map((b, i) => (
            <div className="item" key={i}>
              <span className="cat">{b.proposed_status}</span>
              <br />
              decision {b.decision_id.slice(0, 8)}…
              {b.dependent_id ? ` · dependent ${b.dependent_type}: ${b.dependent_id}` : " · no recorded downstream use"}
              {b.proposed_status === "revalidate" && (
                <div style={{ marginTop: 6 }}>
                  <button onClick={() => revalidate(b.decision_id)}>Revalidate now</button>
                </div>
              )}
            </div>
          ))}
          {blast.caveat && <div className="note">{blast.caveat}</div>}
        </div>
      )}

      <h2 style={{ marginTop: 18 }}>Category boundaries</h2>
      <p className="prose">Choose which facts a rule must name before it can answer automatically. These requirements also apply to existing rules.</p>
      <div className="rule-policy-form" style={{ display: "grid", gap: 8 }}>
        <label>Category<input aria-label="Rule category" value={cat} disabled={saving} onChange={(e) => setCat(e.target.value)} placeholder="category" /></label>
        <div className="bb">{contract?.configured ? "Requirements configured." : "No category requirements configured. Existing rules keep their saved limits."}</div>
        <label>Required boundary fields<input aria-label="Required boundary fields" value={requiredFields} onChange={(e) => setRequiredFields(e.target.value)} placeholder="e.g. project, workspace" /></label>
        <label>Other fields that distinguish fresh confirmations<input aria-label="Fresh confirmation fields" value={evidenceFields} onChange={(e) => setEvidenceFields(e.target.value)} placeholder="e.g. document_kind (optional)" /></label>
        <div className="bb">Required and saved rule boundaries always count. Counters and timestamps do not count unless you explicitly declare them here.</div>
        <label><input type="checkbox" checked={allowGlobal} onChange={(e) => setAllowGlobal(e.target.checked)} /> Allow deliberately confirmed global rules in this category</label>
        <button onClick={saveContract} disabled={!contractReady || saving}>Save category requirements</button>
      </div>

      <h2 style={{ marginTop: 18 }}>New rule</h2>
      <p className="prose" style={{ marginBottom: 8 }}>
        A new category starts in review. Rules use the category's current setting
        and only apply inside their confirmed boundaries.
      </p>
      <div style={{ display: "grid", gap: 8 }}>
        <input value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="keywords, comma separated (e.g. deploy, target)" />
        <input value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="answer value" />
        <ScopeEditor value={scope} onChange={setScope} allowGlobal={contract?.allow_global} required={contract?.required_fields} />
        <button className="primary" onClick={create} disabled={!contractReady || saving}>Create rule</button>
      </div>
      {msg && <div className="note">{msg}</div>}
    </div>
  );
}
