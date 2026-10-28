import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { AgentRow, BlastItem, RuleRow } from "../types";

export function AgentsPanel() {
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [name, setName] = useState("");
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

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Compatible agents</h2>
        <button onClick={load}>Refresh</button>
      </div>
      {error && <div className="empty">{error}</div>}
      {agents.length === 0 && !error && (
        <div className="empty">No agents registered. An agent key identifies a caller — it never grants rule-writing rights.</div>
      )}
      {agents.map((a) => (
        <div className="item" key={a.id}>
          <span className="cat">{a.kind}</span>
          <span className="pri">{a.enabled ? "enabled" : "disabled"}</span>
          <br />
          {a.name}
          <div className="bb">id {a.id.slice(0, 8)}… · scopes {a.scopes_json}</div>
        </div>
      ))}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && register()}
          placeholder="new agent name"
          style={{ flex: 1 }}
        />
        <button className="primary" onClick={register}>Register</button>
      </div>
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
  const [scopeKey, setScopeKey] = useState("");
  const [scopeVal, setScopeVal] = useState("");
  // supersede form (per selected rule)
  const [sel, setSel] = useState<string | null>(null);
  const [newAnswer, setNewAnswer] = useState("");

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

  const scope = () =>
    scopeKey.trim() ? { mandatory: { [scopeKey.trim()]: scopeVal.trim() } } : {};

  const create = async () => {
    const kw = keywords.split(",").map((k) => k.trim()).filter(Boolean);
    if (!kw.length || !answer.trim()) {
      setMsg("Keywords and an answer are required.");
      return;
    }
    await api.createRule({
      category: cat.trim() || "purchase",
      predicate: { keywords: kw },
      answer: { value: answer.trim() },
      scope: scope(),
    });
    setMsg(`Rule created in ${cat}. It applies only inside its scope.`);
    setKeywords("");
    setAnswer("");
    load();
  };

  const supersede = async (r: RuleRow) => {
    if (!newAnswer.trim()) {
      setMsg("Type the corrected answer first.");
      return;
    }
    const out = await api.supersede(r.rule_id, { answer: { value: newAnswer.trim() } });
    setBlast({ ruleId: r.rule_id, items: out.blast_radius.affected });
    setMsg(`Rule corrected → new version. Category is now recalibrating; affected decisions are listed below.`);
    setNewAnswer("");
    load();
  };

  const showBlast = async (r: RuleRow) => {
    const out = await api.blast(r.rule_id);
    setBlast({ ruleId: r.rule_id, items: out.affected, caveat: out.coverage_caveat });
  };

  const revalidate = async (decisionId: string) => {
    const out = await api.revalidate(decisionId);
    setMsg(`Revalidated → ${out.decision}${out.answer?.value ? ` (${out.answer.value})` : ""}: ${out.reason_code}`);
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Rules &amp; corrections</h2>
        <button onClick={load}>Refresh</button>
      </div>
      {rules.length === 0 && (
        <div className="empty">No rules yet. Create one below, or answer an inbox question and choose “remember”.</div>
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
              {r.confirmed_by_human ? "human-confirmed" : "unconfirmed"}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              <button onClick={() => { setSel(sel === r.rule_id ? null : r.rule_id); }}>
                Correct this rule
              </button>
              <button onClick={() => showBlast(r)}>Blast radius</button>
            </div>
            {sel === r.rule_id && (
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <input
                  value={newAnswer}
                  onChange={(e) => setNewAnswer(e.target.value)}
                  placeholder="corrected answer"
                  style={{ flex: 1 }}
                />
                <button className="primary" onClick={() => supersede(r)}>Supersede</button>
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

      <h2 style={{ marginTop: 18 }}>New rule</h2>
      <div style={{ display: "grid", gap: 8 }}>
        <input value={cat} onChange={(e) => setCat(e.target.value)} placeholder="category" />
        <input value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="keywords, comma separated (e.g. deploy, target)" />
        <input value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="answer value" />
        <div style={{ display: "flex", gap: 8 }}>
          <input value={scopeKey} onChange={(e) => setScopeKey(e.target.value)} placeholder="scope field (optional, e.g. env)" style={{ flex: 1 }} />
          <input value={scopeVal} onChange={(e) => setScopeVal(e.target.value)} placeholder="scope value (e.g. staging)" style={{ flex: 1 }} />
        </div>
        <button className="primary" onClick={create}>Create human-confirmed rule</button>
      </div>
      {msg && <div className="note">{msg}</div>}
    </div>
  );
}
