import json
import sqlite3
import uuid
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS agents(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE, scopes_json TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
  actor_type TEXT NOT NULL, actor_id TEXT, event_type TEXT NOT NULL,
  object_type TEXT NOT NULL, object_id TEXT NOT NULL, correlation_id TEXT,
  payload_json TEXT NOT NULL, schema_version INTEGER NOT NULL DEFAULT 1,
  source_evidence_class TEXT);
CREATE TABLE IF NOT EXISTS questions(
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL, agent_id TEXT NOT NULL REFERENCES agents(id),
  canonical_hash TEXT NOT NULL, question_text TEXT NOT NULL, category TEXT NOT NULL,
  intent_type TEXT NOT NULL, risk_class TEXT NOT NULL, reversibility TEXT NOT NULL,
  deadline_at TEXT, options_json TEXT, context_json TEXT, status TEXT NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(agent_id, request_id));
CREATE TABLE IF NOT EXISTS rules(
  id TEXT PRIMARY KEY, category TEXT NOT NULL, created_at TEXT NOT NULL,
  created_by TEXT NOT NULL, active_version_id TEXT, status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE IF NOT EXISTS rule_versions(
  id TEXT PRIMARY KEY, rule_id TEXT NOT NULL REFERENCES rules(id),
  version_number INTEGER NOT NULL, predicate_json TEXT NOT NULL, answer_json TEXT NOT NULL,
  scope_json TEXT NOT NULL, source_type TEXT NOT NULL, evidence_ids_json TEXT NOT NULL DEFAULT '[]',
  confirmed_by_human INTEGER NOT NULL DEFAULT 0, valid_from TEXT NOT NULL, valid_until TEXT,
  supersedes_version_id TEXT, created_at TEXT NOT NULL, UNIQUE(rule_id, version_number));
CREATE TABLE IF NOT EXISTS decisions(
  id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES questions(id),
  mode TEXT NOT NULL, answer_json TEXT, reason_code TEXT NOT NULL, matcher_tier TEXT NOT NULL,
  score REAL, score_kind TEXT, category_stage TEXT NOT NULL, policy_version TEXT NOT NULL,
  latency_ms INTEGER, model_tokens_in INTEGER, model_tokens_out INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decision_rule_uses(
  decision_id TEXT NOT NULL REFERENCES decisions(id), rule_version_id TEXT NOT NULL REFERENCES rule_versions(id),
  match_type TEXT NOT NULL, scope_result_json TEXT NOT NULL, PRIMARY KEY(decision_id, rule_version_id));
CREATE TABLE IF NOT EXISTS receipts(
  id TEXT PRIMARY KEY, decision_id TEXT NOT NULL REFERENCES decisions(id), receipt_type TEXT NOT NULL,
  canonical_action_hash TEXT, action_schema_version INTEGER, why_text TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL DEFAULT '[]', issued_at TEXT NOT NULL, expires_at TEXT,
  revoked_at TEXT, consumed_at TEXT);
CREATE TABLE IF NOT EXISTS attention_items(
  id TEXT PRIMARY KEY, question_id TEXT REFERENCES questions(id), priority_score REAL,
  urgency_class TEXT, earliest_show_at TEXT, deadline_at TEXT, status TEXT NOT NULL DEFAULT 'queued',
  batch_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attention_batches(
  id TEXT PRIMARY KEY, decision_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL, shown_at TEXT, resolved_at TEXT, merge_reason TEXT, compatibility_json TEXT);
CREATE TABLE IF NOT EXISTS decision_dependencies(
  id TEXT PRIMARY KEY, source_receipt_id TEXT NOT NULL REFERENCES receipts(id),
  dependent_type TEXT NOT NULL, dependent_id TEXT NOT NULL, relationship TEXT NOT NULL,
  observed_by TEXT NOT NULL, evidence_class TEXT NOT NULL, created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', UNIQUE(source_receipt_id, dependent_type, dependent_id, relationship));
CREATE TABLE IF NOT EXISTS evidence_items(
  id TEXT PRIMARY KEY, evidence_class TEXT NOT NULL, source_actor_type TEXT NOT NULL,
  source_actor_id TEXT, source_ref TEXT, payload_hash TEXT, payload_excerpt TEXT,
  quality_status TEXT NOT NULL DEFAULT 'unreviewed', created_at TEXT NOT NULL,
  verified_at TEXT, retention_class TEXT NOT NULL DEFAULT 'standard');
CREATE TABLE IF NOT EXISTS feedback_labels(
  id TEXT PRIMARY KEY, decision_id TEXT REFERENCES decisions(id), label_type TEXT NOT NULL,
  label_value TEXT NOT NULL, evidence_id TEXT NOT NULL REFERENCES evidence_items(id),
  eligible_for_calibration INTEGER NOT NULL DEFAULT 0, quarantine_reason TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calibration_examples(
  id TEXT PRIMARY KEY, decision_id TEXT REFERENCES decisions(id), category TEXT NOT NULL,
  preference_epoch TEXT NOT NULL, score REAL, prediction_json TEXT, gold_label TEXT,
  label_source TEXT NOT NULL, weight REAL NOT NULL DEFAULT 1.0, split TEXT NOT NULL DEFAULT 'train',
  is_synthetic INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS category_settings(
  category TEXT PRIMARY KEY, stage TEXT NOT NULL DEFAULT 'shadow', risk_target REAL NOT NULL DEFAULT 0.02,
  locked INTEGER NOT NULL DEFAULT 0, policy_version TEXT NOT NULL, min_evidence_state TEXT NOT NULL DEFAULT 'ok',
  active_preference_epoch TEXT NOT NULL DEFAULT 'epoch-1', updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS autonomy_passports(
  id TEXT PRIMARY KEY, category TEXT NOT NULL, stage TEXT NOT NULL, evidence_summary_json TEXT NOT NULL,
  coverage_estimate REAL, error_estimate REAL, interval_json TEXT, sample_count INTEGER,
  limitations_json TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS away_grants(
  id TEXT PRIMARY KEY, created_by TEXT NOT NULL, starts_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  categories_json TEXT NOT NULL, allowed_intents_json TEXT NOT NULL,
  locked_classes_excluded INTEGER NOT NULL DEFAULT 1, revoked_at TEXT,
  status TEXT NOT NULL DEFAULT 'active', policy_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recalibration_holds(
  id TEXT PRIMARY KEY, category TEXT NOT NULL, rule_id TEXT NOT NULL, new_version_id TEXT,
  scope_fingerprint TEXT NOT NULL, preference_epoch TEXT NOT NULL, required_m INTEGER NOT NULL DEFAULT 1,
  fresh_count INTEGER NOT NULL DEFAULT 0, seen_contexts_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'held', created_at TEXT NOT NULL, released_at TEXT);
CREATE TABLE IF NOT EXISTS canary_runs(
  id TEXT PRIMARY KEY, run_type TEXT NOT NULL, case_id TEXT NOT NULL, category TEXT NOT NULL,
  expected_behavior TEXT NOT NULL, observed_behavior TEXT NOT NULL, passed INTEGER NOT NULL,
  created_at TEXT NOT NULL, evaluation_run_id TEXT);
CREATE TABLE IF NOT EXISTS action_reviews(
  id TEXT PRIMARY KEY, receipt_id TEXT, canonical_action_json TEXT NOT NULL,
  action_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'held', requested_by TEXT NOT NULL,
  approved_by TEXT, approved_at TEXT, execute_not_before TEXT, expires_at TEXT,
  executed_at TEXT, execution_result_json TEXT);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_questions_cat ON questions(category, created_at);
CREATE INDEX IF NOT EXISTS idx_dru_rule ON decision_rule_uses(rule_version_id);
CREATE INDEX IF NOT EXISTS idx_attn_status ON attention_items(status, priority_score, created_at);
CREATE INDEX IF NOT EXISTS idx_dep_receipt ON decision_dependencies(source_receipt_id);
CREATE INDEX IF NOT EXISTS idx_cal_cat ON calibration_examples(category, preference_epoch, split);
"""


class Store:
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def execute(self, sql, params=()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def query(self, sql, params=()):
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def query_one(self, sql, params=()):
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def emit(self, actor_type, actor_id, event_type, object_type, object_id,
             payload=None, evidence_class=None, correlation_id=None):
        eid = new_id()
        ts = now_iso()
        self.conn.execute(
            "INSERT INTO events(id,occurred_at,recorded_at,actor_type,actor_id,event_type,"
            "object_type,object_id,correlation_id,payload_json,schema_version,source_evidence_class)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,1,?)",
            (eid, ts, ts, actor_type, actor_id, event_type, object_type, object_id,
             correlation_id, json.dumps(payload or {}), evidence_class))
        self.conn.commit()
        return eid
