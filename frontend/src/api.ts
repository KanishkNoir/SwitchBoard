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

// Phase 3: conditional reads. The server tags cacheable reads with an ETag
// and answers 304 when nothing changed — the last body stays on screen and
// no re-render fires at all.
const etags = new Map<string, { etag: string; body: unknown }>();

async function get<T>(path: string): Promise<T> {
  const prev = etags.get(path);
  const r = await fetch(path, {
    headers: prev ? { "If-None-Match": prev.etag } : {},
  });
  if (r.status === 304 && prev) return prev.body as T;
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  const body = (await r.json()) as T;
  const etag = r.headers.get("ETag");
  if (etag) etags.set(path, { etag, body });
  return body;
}

export const api = {
  health: () => get<{ status: string; t3_enabled: boolean; capabilities?: string[] }>("/health"),
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
  debrief: () => get<import("./types").DebriefRow[]>("/debrief"),
  onboarding: () => get<import("./types").OnboardingState>("/onboarding"),
  completeOnboarding: (body: unknown) =>
    post<import("./types").OnboardingState>("/onboarding/complete", body),
  answerInbox: (itemId: string, body: unknown) =>
    post<{ decision_id: string; rule?: { action: string } | null }>(`/inbox/${itemId}/answer`, body),
  steering: () => get<import("./types").SteeringSession[]>("/steering"),
  demoSteeringProposal: () => post<import("./types").SteeringSession>("/demo/steering-proposal", {}),
  simulation: () =>
    post<{ run: string; questions: unknown[]; proposals: unknown[]; beats: string[] }>("/demo/simulation", {}),
  steerSession: (id: string, edge: string, magnitude: number) =>
    post<{ instruction: unknown }>(`/steering/${id}/steer`, { edge, magnitude }),
  resolveSteering: (id: string, outcome: "accepted" | "rejected") =>
    post<import("./types").SteeringSession>(`/steering/${id}/resolve`, { outcome }),
  taste: () => get<{ category: string; leans: [string, number][] }[]>("/taste"),
  runEvaluation: () => post<import("./types").EvalReport>("/evaluation/replay", {}),
  revalidate: (decisionId: string) =>
    post<{ decision: string; answer?: { value?: string } | null; reason_code: string }>(
      `/decisions/${decisionId}/revalidate`,
      {}
    ),
};
