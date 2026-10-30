import type { DecisionPayload, GroundedObject, InboxItem, Passport, SteerResult } from "./types";

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return (await r.json()) as T;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return (await r.json()) as T;
}

export const api = {
  health: () => get<{ status: string; t3_enabled: boolean }>("/health"),
  inbox: () => get<InboxItem[]>("/inbox"),
  passport: (category: string) => get<Passport>(`/passport/${encodeURIComponent(category)}`),
  tradeoff: (options: unknown[]) => post<DecisionPayload>("/demo/tradeoff", { options }),
  visual: (goal: string, objects: unknown[]) =>
    post<DecisionPayload>("/demo/visual", { goal, objects }),
  generate: (prompt: string) =>
    post<{ b64_json: string; generated_preview: boolean }>("/demo/visual/generate", { prompt }),
  scout: (goal: string, image_b64: string, phrases: string[], mime?: string) =>
    post<{ payload: DecisionPayload; evidence: { objects: GroundedObject[] } }>("/demo/visual/scout", {
      goal,
      image_b64,
      phrases,
      mime,
    }),
  steerEdit: (image_b64: string, action_id: string, mime?: string) =>
    post<{ b64_json: string; generated_preview: boolean; prompt_used: string }>(
      "/demo/visual/steer-edit",
      { image_b64, action_id, mime }
    ),
  steer: (payload: DecisionPayload, action_id: string) =>
    post<SteerResult>("/demo/steer", { payload, action_id }),
  agents: () => get<import("./types").AgentRow[]>("/human/agents"),
  registerAgent: (name: string, kind: string) =>
    post<{ agent_id: string; api_key: string }>("/api/agents/register", { name, kind }),
  rules: () => get<import("./types").RuleRow[]>("/human/rules"),
  createRule: (body: unknown) => post<{ rule_id: string; version_id: string }>("/rules", body),
  supersede: (ruleId: string, body: unknown) =>
    post<{ version_id: string; blast_radius: { affected: import("./types").BlastItem[] } }>(
      `/rules/${ruleId}/supersede`,
      body
    ),
  blast: (ruleId: string) =>
    get<{ affected: import("./types").BlastItem[]; coverage_caveat: string }>(
      `/rules/${ruleId}/blast-radius`
    ),
  attentionHealth: () => get<import("./types").AttentionHealth>("/human/attention-health"),
  drift: () => get<import("./types").DriftRow[]>("/drift"),
  notices: () => get<import("./types").NoticeItem[]>("/notices"),
  vetoNotice: (itemId: string) => post<{ vetoed: boolean }>(`/notices/${itemId}/veto`, {}),
  dismissNotice: (itemId: string) => post<{ dismissed: boolean }>(`/notices/${itemId}/dismiss`, {}),
  inboxDetail: (itemId: string) => get<Record<string, unknown>>(`/inbox/${itemId}/detail`),
  answerInbox: (itemId: string, body: unknown) =>
    post<{ decision_id: string; rule?: { action: string } | null }>(`/inbox/${itemId}/answer`, body),
  runEvaluation: () => post<import("./types").EvalReport>("/evaluation/replay", {}),
  revalidate: (decisionId: string) =>
    post<{ decision: string; answer?: { value?: string } | null; reason_code: string }>(
      `/decisions/${decisionId}/revalidate`,
      {}
    ),
};
