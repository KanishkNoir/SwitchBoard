export type Edge = "top" | "left" | "right" | "bottom";

export interface DecisionAction {
  action_id: string;
  edge: Edge;
  label: string;
  intent: string;
  parameter_delta: Record<string, number>;
  expected_effect: string;
  requires_confirmation: boolean;
}

export interface TradeOption {
  id: string;
  price?: number;
  comfort?: number;
  complexity?: number;
  novelty?: number;
}

export interface DecisionPayload {
  question_id: string;
  agent_id: string;
  task_id: string;
  question: string;
  context_summary?: string;
  evidence?: unknown[];
  visual_assets?: unknown[];
  actions: DecisionAction[];
  risk_class?: string;
  reversibility?: string;
  _options?: TradeOption[];
  _weights?: Record<string, number>;
}

export interface GroundedObject {
  id: string;
  label: string;
  bbox: { x1: number; y1: number; x2: number; y2: number; w: number; h: number };
  mask_encoding?: string;
  mask_data_len?: number;
  overlay_png_b64?: string;
}

export interface InboxItem {
  id: string;
  question_id: string;
  question_text: string;
  category: string;
  priority_score: number;
  batch_id?: string | null;
  deadline_at?: string | null;
}

export interface Passport {
  category: string;
  stage: string;
  locked: boolean;
  risk_target: number;
  preference_epoch: string;
  evidence_state: string;
  gold_sample_count: number;
  limitations: string[];
  policy_version: string;
}

export interface AgentRow {
  id: string;
  name: string;
  kind: string;
  scopes_json: string;
  enabled: number;
  created_at: string;
}

export interface RuleRow {
  rule_id: string;
  category: string;
  status: string;
  version_id: string;
  version_number: number;
  predicate_json: string;
  answer_json: string;
  scope_json: string;
  source_type: string;
  confirmed_by_human: number;
}

export interface BlastItem {
  decision_id: string;
  dependent_id?: string | null;
  dependent_type?: string;
  proposed_status: string;
}

export interface EvalRow {
  strategy: string;
  total: number;
  auto_answered: number;
  coverage: number;
  interruptions_deferred: number;
  wrong_auto: number;
  wrong_auto_rate: number;
  wrong_auto_ci95: [number, number];
  stale_after_flip: number;
  out_of_scope_auto: number;
  blast_radius_recall: number | null;
  mean_recovery_questions?: number | null;
  label_contamination?: number;
  note?: string;
}

export interface EvalReport {
  strategies: EvalRow[];
  ablations: EvalRow[];
  stress?: (EvalRow & { suite: string })[];
  episodes?: Record<
    string,
    { episodes: number; mean_coverage: number; wrong_auto: number; deferrals: number; mean_recovery_questions: number | null }
  >;
  is_synthetic: boolean;
  notes: string[];
}

export interface SteerResult {
  status: string;
  action_id?: string;
  edge?: Edge;
  weights?: Record<string, number>;
  ranked_option_ids?: string[];
}
