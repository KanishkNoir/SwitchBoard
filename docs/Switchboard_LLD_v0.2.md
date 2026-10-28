# Low-Level Design
**Switchboard — Data Model, APIs and Decision Logic v0.2**  
Version: 0.2 draft | Date: 28 October 2026 | Status: Proposed implementation contract

## 1. Purpose and implementation baseline

This LLD defines the implementation contract for the architecture in `Switchboard_HLD_v0.2`. It extends the original v0.1 tables and APIs rather than pretending that the added capabilities already exist in code. Names marked **proposed** are new v0.2 work. Keep the implementation small enough for a hackathon, but preserve event history, provenance and testable interfaces from the start.

**Baseline stack:** Python, FastAPI, official MCP SDK, SQLite in WAL mode, local text encoder, PWA and SSE. Optional model providers are adapters behind flags. Model/API access, allowed data types and current provider terms must be checked before activation.

## 2. Package layout

Suggested layout:

```text
switchboard/
  app.py                     # FastAPI app and lifecycle
  config.py                  # policy/config loading
  auth.py                    # agent identities, key validation, scopes
  mcp_server.py              # MCP tools and schemas
  api/                       # HTTP routes and response models
  domain/
    questions.py             # canonical question/action models
    rules.py                 # immutable rule versions and scope predicates
    decisions.py             # decision outcomes and receipts
    policies.py              # locks, category stage, Away grants
    attention.py             # queue priority and safe grouping
    dependencies.py          # rule-use lineage and impact traversal
    evidence.py              # evidence classes, label eligibility
    passport.py              # autonomy-stage projection
  matching/
    t0_rules.py
    t1_encoder.py
    t2_open_model.py         # optional
    t3_hosted_model.py       # optional
    ladder.py
  governor/
    risk.py
    calibration.py
    stage_machine.py
  persistence/
    db.py
    schema.sql
    repositories.py
    event_store.py
  evaluation/
    replay.py
    baselines.py
    metrics.py
    fixtures/
  ui/                         # PWA source
  tests/
    unit/
    integration/
    security/
    evaluation/
```

Domain logic must not depend directly on FastAPI, MCP SDK or a model provider. Adapters translate external input into domain objects and serialize domain decisions into transport-specific responses.

## 3. Canonical request and response models

### 3.1 `QuestionRequest` (proposed v0.2)

| Field | Type | Required | Notes |
|---|---|---:|---|
| `request_id` | string/UUID | Yes | Caller-generated idempotency key; repeated same payload returns original decision. |
| `question` | string | Yes | Plain text data; never interpreted as system instruction. Length-limited. |
| `category` | string | Yes | User-configured category; unknown categories default to Suggest/Defer. |
| `risk_hint` | enum | No | Caller hint only; cannot lower Switchboard's risk classification. |
| `reversibility` | enum | No | `reversible`, `partially_reversible`, `irreversible`, `unknown`; unknown is conservative. |
| `deadline_at` | ISO-8601/null | No | Used by attention scheduler; validated and timezone-aware. |
| `options` | list of option objects | No | Stable option IDs and labels, not free text alone. |
| `context` | structured object | No | Minimized context fields, not arbitrary full page dumps. |
| `intent_type` | enum | No | `preference`, `permission`, `disambiguation`, `action_review`, `unknown`. |
| `action` | object/null | No | Canonical proposed action for sandbox action review only. |
| `parent_receipts` | list of UUIDs | No | Decisions this request depends on. |
| `metadata` | object | No | Allowlisted small fields only; size and schema limits apply. |

The authenticated agent ID is derived from credentials and must not be trusted from caller-supplied JSON.

### 3.2 Response contract

```json
{
  "decision": "answer | defer | deny",
  "answer": {"option_id": "...", "value": "..."},
  "reason_code": "matched_rule | locked | below_policy | out_of_scope | ...",
  "receipt_id": "uuid",
  "question_id": "uuid",
  "rule_versions": ["uuid"],
  "matcher_tier": "T0 | T1 | T2 | T3 | none",
  "score": 0.91,
  "score_kind": "similarity | calibrated_estimate | none",
  "stage": "shadow | suggest | auto",
  "requires_human": true,
  "expires_at": null,
  "batch_id": null,
  "explanation": "Short human-readable reason"
}
```

Fields are illustrative. In `defer` and `deny` responses, `answer` is omitted or null. `score` is not automatically a probability. Receipts include policy version, evidence IDs, scope evaluation and timestamps. Do not expose hidden reasoning or chain-of-thought; explanations should be concise and based on logged decision factors.

### 3.3 Normalization

- Unicode normalize; trim whitespace; normalize stable option IDs and timestamps.
- Preserve raw input only where retention policy allows; store a hash when the raw payload is not required.
- Derive canonical category/context with allowlisted fields.
- Treat free-form content, image/OCR text and agent descriptions as untrusted data.
- Hash canonical payload for idempotency and action-bound receipts.
- Do not use normalization to silently change legal names, amounts, recipients or other semantically significant fields.

## 4. Relational data model

SQLite is the source of truth for the v1 local instance. Use foreign keys, parameterized SQL and transaction boundaries. Append-only event records preserve historical truth; query tables are projections that can be rebuilt.

### 4.1 Core tables

#### `agents`
- `id TEXT PRIMARY KEY`
- `name TEXT NOT NULL`
- `kind TEXT NOT NULL`
- `key_hash TEXT NOT NULL UNIQUE`
- `scopes_json TEXT NOT NULL`
- `enabled INTEGER NOT NULL DEFAULT 1`
- `created_at TEXT NOT NULL`
- Never store plaintext API keys.

#### `events`
- `id TEXT PRIMARY KEY`
- `occurred_at TEXT NOT NULL`
- `recorded_at TEXT NOT NULL`
- `actor_type TEXT NOT NULL` (`human`, `agent`, `system`, `tool`, `model`, `evaluation`)
- `actor_id TEXT`
- `event_type TEXT NOT NULL`
- `object_type TEXT NOT NULL`
- `object_id TEXT NOT NULL`
- `correlation_id TEXT`
- `payload_json TEXT NOT NULL`
- `schema_version INTEGER NOT NULL`
- `source_evidence_class TEXT`
- `prev_event_hash TEXT` optional for tamper-evidence research; not a substitute for secure storage

#### `questions`
- `id TEXT PRIMARY KEY`
- `request_id TEXT NOT NULL`
- `agent_id TEXT NOT NULL REFERENCES agents(id)`
- `canonical_hash TEXT NOT NULL`
- `question_text TEXT NOT NULL`
- `category TEXT NOT NULL`
- `intent_type TEXT NOT NULL`
- `risk_class TEXT NOT NULL`
- `reversibility TEXT NOT NULL`
- `deadline_at TEXT`
- `options_json TEXT`
- `context_json TEXT`
- `status TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `UNIQUE(agent_id, request_id)`

#### `rules`
- `id TEXT PRIMARY KEY` stable identity across versions
- `category TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `created_by TEXT NOT NULL`
- `active_version_id TEXT`
- `status TEXT NOT NULL`

#### `rule_versions`
- `id TEXT PRIMARY KEY`
- `rule_id TEXT NOT NULL REFERENCES rules(id)`
- `version_number INTEGER NOT NULL`
- `predicate_json TEXT NOT NULL`
- `answer_json TEXT NOT NULL`
- `scope_json TEXT NOT NULL`
- `source_type TEXT NOT NULL` (`swipe`, `explicit_edit`, `voice_confirmed`, `image_confirmed`, `backfill`, `system_proposal`)
- `evidence_ids_json TEXT NOT NULL`
- `confirmed_by_human INTEGER NOT NULL DEFAULT 0`
- `valid_from TEXT NOT NULL`
- `valid_until TEXT`
- `supersedes_version_id TEXT`
- `created_at TEXT NOT NULL`
- `UNIQUE(rule_id, version_number)`

#### `decisions`
- `id TEXT PRIMARY KEY`
- `question_id TEXT NOT NULL REFERENCES questions(id)`
- `mode TEXT NOT NULL` (`auto`, `human`, `suggested`, `deferred`, `denied`, `shadow`)
- `answer_json TEXT`
- `reason_code TEXT NOT NULL`
- `matcher_tier TEXT NOT NULL`
- `score REAL`
- `score_kind TEXT`
- `category_stage TEXT NOT NULL`
- `policy_version TEXT NOT NULL`
- `latency_ms INTEGER`
- `model_tokens_in INTEGER`
- `model_tokens_out INTEGER`
- `created_at TEXT NOT NULL`

#### `decision_rule_uses`
- `decision_id TEXT NOT NULL REFERENCES decisions(id)`
- `rule_version_id TEXT NOT NULL REFERENCES rule_versions(id)`
- `match_type TEXT NOT NULL` (`exact`, `scope`, `semantic`, `human_selected`)
- `scope_result_json TEXT NOT NULL`
- `PRIMARY KEY(decision_id, rule_version_id)`

#### `receipts`
- `id TEXT PRIMARY KEY`
- `decision_id TEXT NOT NULL REFERENCES decisions(id)`
- `receipt_type TEXT NOT NULL` (`answer`, `action_approval`, `defer`, `deny`)
- `canonical_action_hash TEXT`
- `action_schema_version INTEGER`
- `why_text TEXT NOT NULL`
- `evidence_ids_json TEXT NOT NULL`
- `issued_at TEXT NOT NULL`
- `expires_at TEXT`
- `revoked_at TEXT`
- `consumed_at TEXT`
- `undo_deadline TEXT` optional; not equivalent to external rollback

### 4.2 Attention, dependency and evidence tables

#### `attention_items`
- `id TEXT PRIMARY KEY`, `question_id TEXT REFERENCES questions(id)`, `priority_score REAL`, `urgency_class TEXT`, `earliest_show_at TEXT`, `deadline_at TEXT`, `status TEXT`, `batch_id TEXT`, `created_at TEXT`, `updated_at TEXT`.

#### `attention_batches`
- `id TEXT PRIMARY KEY`, `decision_key TEXT`, `status TEXT`, `created_at TEXT`, `shown_at TEXT`, `resolved_at TEXT`, `merge_reason TEXT`, `compatibility_json TEXT`.

#### `decision_dependencies`
- `id TEXT PRIMARY KEY`, `source_receipt_id TEXT NOT NULL REFERENCES receipts(id)`, `dependent_type TEXT NOT NULL`, `dependent_id TEXT NOT NULL`, `relationship TEXT NOT NULL`, `observed_by TEXT NOT NULL`, `evidence_class TEXT NOT NULL`, `created_at TEXT NOT NULL`, `status TEXT NOT NULL`.
- Unique indexes prevent duplicate dependency edges. The system must represent missing coverage explicitly; lack of an edge does not mean unaffected.

#### `evidence_items`
- `id TEXT PRIMARY KEY`, `evidence_class TEXT NOT NULL`, `source_actor_type TEXT NOT NULL`, `source_actor_id TEXT`, `source_ref TEXT`, `payload_hash TEXT`, `payload_excerpt TEXT`, `quality_status TEXT NOT NULL`, `created_at TEXT NOT NULL`, `verified_at TEXT`, `retention_class TEXT NOT NULL`.
- Avoid storing raw attachment content unless needed and consented; source references may point to locally stored files.

#### `feedback_labels`
- `id TEXT PRIMARY KEY`, `decision_id TEXT REFERENCES decisions(id)`, `label_type TEXT NOT NULL`, `label_value TEXT NOT NULL`, `evidence_id TEXT NOT NULL REFERENCES evidence_items(id)`, `eligible_for_calibration INTEGER NOT NULL DEFAULT 0`, `quarantine_reason TEXT`, `created_at TEXT NOT NULL`.

#### `calibration_examples`
- `id TEXT PRIMARY KEY`, `decision_id TEXT REFERENCES decisions(id)`, `category TEXT NOT NULL`, `preference_epoch TEXT NOT NULL`, `score REAL`, `prediction_json TEXT`, `gold_label TEXT`, `label_source TEXT NOT NULL`, `weight REAL NOT NULL DEFAULT 1.0`, `split TEXT NOT NULL`, `is_synthetic INTEGER NOT NULL DEFAULT 0`, `created_at TEXT NOT NULL`.
- Only curated policy-eligible labels join the gold set. `agent_asserted` and `model_inferred` default to `eligible_for_calibration=0`.

### 4.3 Policy and lifecycle tables

#### `category_settings`
- `category TEXT PRIMARY KEY`
- `stage TEXT NOT NULL` (`shadow`, `suggest`, `auto`)
- `risk_target REAL NOT NULL`
- `locked INTEGER NOT NULL DEFAULT 0`
- `policy_version TEXT NOT NULL`
- `min_evidence_state TEXT NOT NULL`
- `active_preference_epoch TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

#### `autonomy_passports`
- `id TEXT PRIMARY KEY`, `category TEXT NOT NULL`, `stage TEXT NOT NULL`, `evidence_summary_json TEXT NOT NULL`, `coverage_estimate REAL`, `error_estimate REAL`, `interval_json TEXT`, `sample_count INTEGER`, `limitations_json TEXT NOT NULL`, `reason TEXT NOT NULL`, `created_at TEXT NOT NULL`.

#### `away_grants`
- `id TEXT PRIMARY KEY`, `created_by TEXT NOT NULL`, `starts_at TEXT NOT NULL`, `expires_at TEXT NOT NULL`, `categories_json TEXT NOT NULL`, `allowed_intents_json TEXT NOT NULL`, `locked_classes_excluded INTEGER NOT NULL DEFAULT 1`, `revoked_at TEXT`, `status TEXT NOT NULL`, `policy_version TEXT NOT NULL`.

#### `canary_runs`
- `id TEXT PRIMARY KEY`, `run_type TEXT NOT NULL` (`shadow`, `sandbox`), `case_id TEXT NOT NULL`, `category TEXT NOT NULL`, `expected_behavior TEXT NOT NULL`, `observed_behavior TEXT NOT NULL`, `passed INTEGER NOT NULL`, `created_at TEXT NOT NULL`, `evaluation_run_id TEXT`.

#### `action_reviews` (sandbox-only)
- `id TEXT PRIMARY KEY`, `receipt_id TEXT NOT NULL REFERENCES receipts(id)`, `canonical_action_json TEXT NOT NULL`, `action_hash TEXT NOT NULL`, `status TEXT NOT NULL`, `requested_by TEXT NOT NULL`, `approved_by TEXT`, `approved_at TEXT`, `execute_not_before TEXT`, `expires_at TEXT`, `executed_at TEXT`, `execution_result_json TEXT`.

### 4.4 Indexes

Create indexes on `events(event_type, occurred_at)`, `questions(agent_id, request_id)`, `questions(category, created_at)`, `rule_versions(rule_id, version_number)`, `decisions(question_id, created_at)`, `decision_rule_uses(rule_version_id)`, `attention_items(status, priority_score, created_at)`, `decision_dependencies(source_receipt_id)`, `feedback_labels(eligible_for_calibration, label_type)`, and `calibration_examples(category, preference_epoch, split)`.

## 5. Event types

Event log is append-only. Suggested event types:

- `agent.registered`, `agent.disabled`, `agent.key_rotated`
- `question.received`, `question.normalized`, `question.rejected`
- `attention.item_queued`, `attention.items_clustered`, `attention.batch_shown`, `attention.batch_split`, `attention.item_resolved`
- `rule.proposed`, `rule.confirmed`, `rule.version_created`, `rule.superseded`, `rule.scope_changed`
- `decision.shadow_logged`, `decision.suggested`, `decision.auto_answered`, `decision.deferred`, `decision.denied`
- `decision.rule_used`, `decision.dependency_recorded`, `decision.revalidation_queued`, `decision.revalidated`, `decision.marked_stale`
- `feedback.received`, `feedback.quarantined`, `feedback.admitted_to_calibration`, `feedback.rejected_for_calibration`
- `calibration.epoch_started`, `calibration.estimate_updated`, `category.promoted`, `category.demoted`, `category.frozen`
- `away.grant_created`, `away.grant_revoked`, `away.grant_expired`
- `action.review_requested`, `action.approved`, `action.hash_mismatch`, `action.held`, `action.released`, `action.cancelled`, `action.executed`
- `canary.started`, `canary.completed`, `evaluation.started`, `evaluation.completed`

Event payloads include schema version and only allowlisted data. Projection updates should be replayable and idempotent.

## 6. API contracts

### 6.1 MCP tool: `ask`

Input: canonical `QuestionRequest`. Output: `DecisionResponse`.

Rules:
- Authenticate agent outside the input JSON.
- Idempotency key is `(agent_id, request_id)`. Same request + same canonical hash returns prior result. Same key + different hash returns `IDEMPOTENCY_CONFLICT`.
- Hard-lock checks precede rule matching.
- Every answer/defer/deny produces a receipt and audit event.
- Shadow stage logs prediction and returns defer; it must not leak candidate answer as an effective instruction unless explicitly in the local UI's Shadow diagnostics.

### 6.2 MCP tool: `get_rules`

Input: optional `category`, `include_superseded=false`, `scope_context`, `limit`.

Output: only rules the authenticated agent is allowed to read. Superseded rules are omitted by default. When a rule needs to be disclosed for debugging, its status and version must be explicit. It is read-only for agents.

### 6.3 MCP tool: `report_outcome`

Input example:

```json
{
  "decision_id": "uuid",
  "outcome": "success | failure | unknown",
  "detail": "optional short description",
  "evidence_ref": null
}
```

Behavior: store as `agent_asserted` by default. Do not directly create a gold calibration label. If a trusted adapter validates the outcome, it calls the internal verifier to attach a separate `tool_verified` evidence item. A user correction is a separate route/event.

### 6.4 Proposed MCP tool: `record_use`

Purpose: let a compatible agent record that a prior decision receipt influenced a downstream object or action.

Input: `receipt_id`, `dependent_type`, `dependent_id`, `relationship`, `status`, minimal `context`.

Behavior: authenticate caller; verify receipt exists and is visible to this agent; append dependency edge with `observed_by=agent` and evidence class `agent_asserted`; if a tool adapter verifies the dependency, add a separate verified edge. This is best-effort and must not be presented as exhaustive impact coverage.

### 6.5 Proposed sandbox MCP/HTTP endpoint: `request_action_review`

Input: normalized action object, canonicalization version, request id, reversibility, recipient/entity identity, amount/resource if relevant, and dependent receipt IDs.

Behavior:
1. Apply hard locks and policy.
2. Canonicalize deterministic fields.
3. Store action hash and exact canonical request.
4. In v1, return hold/defer unless sandbox policy and explicit human approval permit it.
5. At execution time, executor re-canonicalizes actual action and verifies hash, receipt status, expiry, revocation and current policy.
6. Any mismatch blocks execution and requires a fresh review.

### 6.6 HTTP API for the PWA

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Local liveness, no secrets. |
| GET | `/inbox` | Prioritized unresolved questions and batches. |
| POST | `/inbox/{id}/answer` | Answer/clarify/deny/postpone; creates human feedback event. |
| POST | `/inbox/{id}/reason` | Record structured denial/correction reason. |
| POST | `/away/grants` | Create scoped, expiring grant. |
| POST | `/away/grants/{id}/revoke` | Revoke grant; enforcement checks revocation at decision time. |
| PUT | `/settings/{category}` | Update stage or risk target with validation and audit. |
| GET | `/passport/{category}` | Read autonomy passport. |
| GET | `/rules/{id}/blast-radius` | View dependent decisions and completeness warning. |
| POST | `/rules/{id}/supersede` | Human-confirmed correction/scope change. |
| POST | `/decisions/{id}/revalidate` | Queue selective revalidation. |
| GET | `/wrapped` | Aggregate product stats with sample limitations. |
| GET | `/stream` | SSE live updates; local authenticated origin only. |
| POST | `/evaluation/replay` | Start a local replay job if enabled. |

For a hackathon MVP, routes may be implemented in phases; no UI should expose a button whose backend semantics are not implemented.

### 6.7 Error responses

Use typed errors: `INVALID_SCHEMA`, `UNAUTHENTICATED`, `FORBIDDEN_SCOPE`, `IDEMPOTENCY_CONFLICT`, `LOCKED_ACTION`, `RULE_SCOPE_MISMATCH`, `STALE_RULE_VERSION`, `GRANT_EXPIRED`, `GRANT_REVOKED`, `MODEL_UNAVAILABLE`, `POLICY_EVIDENCE_INSUFFICIENT`, `ACTION_HASH_MISMATCH`, `NOT_FOUND`, `INTERNAL_FAIL_CLOSED`.

Errors that affect a decision return no positive authorization. Internal failures are recorded without including sensitive prompt content in logs.

## 7. Decision algorithm

### 7.1 Decision path

```python
def handle_ask(request, authenticated_agent):
    q = validate_and_canonicalize(request, authenticated_agent)
    prior = idempotency_lookup(authenticated_agent.id, q.request_id)
    if prior:
        if prior.canonical_hash == q.canonical_hash:
            return prior.response
        raise IdempotencyConflict()

    risk = classify_risk_conservatively(q)
    if risk.is_locked:
        return persist_defer(q, reason="locked", human_required=True)

    attention_result = attention_scheduler.register(q)
    if attention_result.requires_human_now:
        return persist_defer(q, reason=attention_result.reason, human_required=True)

    candidate = rule_matcher.find_candidate(q)
    if candidate and not evaluate_scope(candidate.rule_version.scope, q).valid:
        candidate = None

    if candidate is None:
        candidate = matcher_ladder.resolve(q)  # T0 -> T1 -> optional T2 -> optional T3

    stage = category_policy.current_stage(q.category)
    if integrity_service.is_quarantined(q.category):
        return persist_defer(q, reason="feedback_integrity_hold", human_required=True)
    if category_policy.requires_recalibration(q.category):
        return persist_defer(q, reason="recalibration_pending", human_required=True)
    if stage == "shadow":
        persist_shadow_prediction(q, candidate)
        return persist_defer(q, reason="shadow", human_required=True)
    if stage == "suggest":
        return persist_suggestion_as_defer(q, candidate)
    if stage == "auto" and candidate and policy_evaluator.is_eligible(q, candidate):
        return persist_answer_with_receipt(q, candidate)
    return persist_defer(q, reason="below_policy", human_required=True)
```

This is illustrative orchestration. The production implementation must ensure atomicity around active rule versions and category policy, and must not return an answer if a concurrent supersession occurred between matching and persistence.

### 7.2 Risk policy

- `LOCK` classes are not learnable by a preference matcher.
- `risk_hint` from the caller never reduces a risk classification.
- Unknown or contradictory reversibility is treated conservatively.
- Away grant scope is checked after locks and before any eligible automation.
- Action execution authorization is separate from answering a preference question.

### 7.3 Matcher ladder

Each tier returns `{candidate, score, score_kind, evidence_ids, model_id, latency_ms, failure}`. Tier ordering is configurable and testable. Only continue if current tier is uncertain or unavailable; failures cannot become low-confidence approvals. T0 exact rules are deterministic. T1 similarity scores are not probabilities. T2/T3 model agreement or log-probability use is disabled until access and calibration assumptions are validated.

### 7.4 Scope evaluation

`scope_json` supports mandatory predicates and optional context qualifiers. Mandatory predicate failure makes the candidate ineligible, irrespective of semantic similarity. Missing required context yields `unknown`, not `true`. The UI can ask the user whether the new context belongs in the rule's scope; confirmed changes create a new version.

### 7.5 Attention grouping and scheduling

Grouping criteria:
- Same underlying decision entity or an explicit shared choice dimension.
- Compatible options and constraints.
- No conflicting deadlines or incompatible risk classes.
- Rule scope is consistent across child questions.
- Candidate merge can be explained in structured terms.

Priority must preserve hard overrides for critical/time-sensitive items. A scoring function can rank remaining queue items, but it cannot demote a hard override. Test false merges and late critical interruptions as first-class failure modes.

### 7.6 Preference supersession and calibration

At supersession time, increment the category's preference epoch and record the old/new rule linkage. The calibration adapter selects one experimental strategy per run:
- Static window.
- Generic adaptive baseline.
- Supersession-triggered reset.
- Down-weight historical examples (original v0.1 proposed weight 0.2) and remain ask-only until fresh confirmed evidence (original v0.1 proposed default `m=5`).

Do not hardcode the research treatment into persistence code. Store policy version and strategy in the evaluation run. The 0.2 weight and five-example recovery count remain experimental defaults, not scientifically established values.

### 7.7 Statistical reporting

- Define the denominator for wrong-auto rate: eligible automatic answers with an adjudicated correctness label.
- Display point estimates and uncertainty intervals; show sample count and missing-label rate.
- Do not interpret `(errors + 1) / (n + 1)` alone as a universal guarantee of true error below alpha.
- Do not promote a category based only on a small number of zero-error examples.
- Analyze repeated observations per user/category and preference epoch; do not blindly treat correlated decisions as independent.
- Report coverage/error trade-offs and failure cases, including where coverage at the configured target is too low.

## 8. Blast-radius algorithm

1. Load superseded rule version and its known scope.
2. Query `decision_rule_uses` for decisions that referenced that version.
3. Join `decision_dependencies` to find recorded downstream objects/actions.
4. Filter by object state: pending, completed, failed, unknown.
5. Re-evaluate whether the new rule changes the original decision under the original context.
6. Emit a proposed status: `unaffected`, `revalidate`, `review_completed`, `unknown_dependency_coverage`.
7. Enqueue pending work and surface a blast-radius card to the user.
8. Never automatically modify a completed external action in v1.

The graph is only as complete as the receipts and dependency edges captured by agents and adapters. Passport and UI must display coverage limitations.

## 9. Feedback integrity and canary logic

### Evidence policy
- Human confirmation/correction: eligible as intent label, subject to scope and ambiguity checks.
- Trusted tool observation: eligible for execution-state labels, not automatically for intent correctness.
- Agent assertion: diagnostic by default; not gold.
- Model inference: proposed label, not gold until human adjudication.
- Synthetic traces: evaluation only, never real-world evidence.

### Rubber-stamp indicators
Potential signals include high approval ratio, very short decision latency, repeated default-option selection, low evidence-view engagement, many post-action reversals and canary failures. None alone proves rubber-stamping.

### Canary execution
- Run only against shadow predictions or sandbox actions with known expected outcomes.
- Mark every canary and expected behavior in the event log.
- Keep canaries out of preference learning and normal user-quality metrics.
- If the system fails a canary, freeze/demote the relevant category per configured policy and raise an integrity event.
- Tune false positive/negative rates in offline evaluation; avoid using deception or known-wrong real-world actions as live probes.

## 10. Action binding and hold-and-release (sandbox only)

Canonical action representation must contain all authorization-relevant fields: action type, target/recipient/entity, parameters, amounts, destination, attached content hash if applicable, and canonicalization version. Canonical JSON ordering and numeric/date formatting must be specified and covered by tests.

Approval flow:
1. Build canonical request and calculate SHA-256 (or approved cryptographic hash).
2. Store exact canonical action, hash, approver, issue time, scope and expiry in receipt.
3. When executing, canonicalize the actual action again and compare hashes.
4. Re-check expiry/revocation/current policy and one-use consumption in a transaction.
5. Mismatch, missing receipt, stale policy or repeat consumption blocks execution.
6. For hold-and-release, the hold is a queue state; nothing has been sent. Before release, repeat authorization and action-hash verification.

This mechanism can enforce only where the executor is controlled by Switchboard or an integrated adapter. It cannot guarantee enforcement inside a closed agent or arbitrary website.

## 11. Privacy, retention and local security

- Bind by loopback by default; use authenticated network access only when configured.
- Store agent secrets as salted hashes or verifier-safe hashes; rotate/revoke keys.
- Use SQLite parameterized queries and restrict arbitrary file/path access.
- Do not log raw voice, image or page content unless explicitly needed, consented and retention-bounded.
- Store evidence references/hashes and minimal excerpts; user can inspect and delete raw artifacts without erasing required audit metadata if deletion policy permits.
- Model egress is off until explicitly configured. Redact unnecessary identifiers and only send minimum structured content.
- PWA endpoints require CSRF/origin protections where applicable; SSE must be authenticated and not expose agent keys.
- Secure against prompt injection by keeping system instructions/policy out of user-controlled content and by treating extracted text as untrusted data.
- Backup/export requires a deliberate user action. Document the backup's sensitivity and encryption choice.

## 12. Test plan

### Unit tests
- Canonicalization and idempotency; stable option IDs; timestamps; action hash.
- Hard-lock precedence over stage, matches and Away grants.
- Scope predicate true/false/unknown behavior.
- Supersession preserves history and updates active version.
- Evidence class eligibility.
- Attention priority and merge compatibility.
- Passport promotion/demotion state transitions.

### Integration tests
- MCP stdio and Streamable HTTP calls from two different harness adapters.
- Concurrent requests for the same idempotency key.
- Supersession concurrent with ask; no stale answer after commit.
- Rule change triggers blast-radius query and revalidation queue.
- Expired/revoked Away grant cannot answer automatically.
- Action hash mismatch blocks sandbox execution.
- Agent self-report cannot create gold label.
- Model unavailability produces defer.

### Security tests
- Prompt injection in question/context/document cannot alter hard locks or write rules.
- Agent cannot read another agent's unauthorized data or modify rules.
- Replayed or expired receipt cannot be consumed twice.
- SSE and UI cannot leak credentials or private evidence across sessions.
- Oversized payloads, malformed JSON, path traversal and SQL injection attempts fail safely.

### Evaluation tests
- Synthetic preference flips with ground-truth scope.
- Near-duplicate questions where batch merge is correct versus incorrect.
- Critical question with deadline that must bypass batching.
- Canary contamination scenarios.
- Noisy agent-reported success and disagreement with tool/user evidence.
- Matched baseline replay with the same traces and model budget.

## 13. Migration from v0.1

1. Preserve existing `agents`, `events`, `questions`, `decisions`, `rules`, `calibration`, `settings` and `receipts` data.
2. Introduce `rule_versions` and backfill each existing rule into an initial version with `source_type` mapped from existing `source`; leave unknown confirmation status false.
3. Create `decision_rule_uses` from existing `decisions.rule_ids` where the mapping is reliable; mark incomplete dependency coverage instead of fabricating edges.
4. Extend receipts with type/hash/version/evidence/expiry fields; existing receipts remain non-action authorization receipts unless a valid action hash and approver record exist.
5. Migrate outcomes from `report_outcome` to `agent_asserted` evidence unless independently verified.
6. Map existing category `alpha`, `stage`, and `locked` into versioned category settings; retain historical settings in events.
7. Create Autonomy Passport projections from known data; mark missing evidence and unknown confidence rather than synthesizing metrics.
8. Run migration on a copy and validate row counts, foreign keys and replay determinism before replacing the local database.

## 14. Implementation sequence

### Phase 1 — durable core
- Schema migrations, event log, MCP authentication and validated `ask`.
- Hard locks, local T0 rules, receipts and fail-closed behavior.

### Phase 2 — rules and adaptation
- Immutable rule versions, scope predicates, T1 matcher adapter, supersession event and calibration strategy interface.
- Shadow replay harness and baseline metrics.

### Phase 3 — attention and impact
- Priority queue, conservative clustering, batch UI and basic decision-to-rule dependency lineage.
- Blast-radius screen for pending tasks.

### Phase 4 — integrity and transparency
- Evidence classes, quarantine, sandbox-only canaries, Autonomy Passport.
- Regression test generation from user-confirmed corrections.

### Phase 5 — integration and demo
- Two compatible agent harnesses if feasible; one simulated task that shows repeated questions, preference change, blast radius and safer revalidation.
- Run baseline replay, security tests and report limitations honestly.

## 15. Definition of done for v0.2

- A compatible agent can call `ask` and receive a typed answer/defer with a receipt.
- A user correction creates a new version and preserves the historical rule.
- Scope failure prevents semantic similarity from automatically reusing the rule.
- Deferred questions are ranked; only safely equivalent questions are merged.
- A superseded rule can surface known downstream decisions with coverage caveats.
- Agent self-reports are not treated as gold correctness labels.
- A canary failure in the sandbox can freeze/demote category automation.
- Passport explains stage, evidence, limitations and latest transition reason.
- Hard locks are tested across all paths; errors fail closed.
- Evaluation compares the proposed method with explicit baselines and labels synthetic traces.
- Documentation does not claim a 2% population error guarantee without supporting evidence.


## 16. Meta-model agent adapters and directional UI contracts

### 16.1 Agent set for the hackathon

Implement two Switchboard-native agents first: `visual_scout` and `tradeoff_planner`. A `coding_direction` agent is stretch scope. Native agents are ordinary application workflows using the Meta Model API, not separate product-level model services. Do not require the consumer Muse app. Muse Code integration is conditional on confirming a supported extension/tool interface; no brittle screen scraping or assumed interception.

### 16.2 Canonical decision payload

Each agent must submit a validated object with: `question_id`, `agent_id`, `task_id`, `question`, `context_summary`, `evidence[]`, `visual_assets[]`, `actions[]`, `deadline`, `risk_class`, `reversibility`, and `downstream_refs[]`. Each action includes `action_id`, `edge` (`top|left|right|bottom`), `label`, `intent`, `parameter_delta`, `expected_effect`, and `requires_confirmation`. Reject unknown edge names, missing action labels, duplicate IDs, oversized media, and free-form fields that attempt to change policy. A model-generated action is a proposal; the deterministic policy layer validates it before display.

### 16.3 Gesture semantics

The edge is a spatial affordance, not a universal semantic. For each question, the agent proposes a bounded action set and Switchboard renders the exact label adjacent to that edge. Example for a room redesign: left = lower budget, right = improve comfort, top = explore a bolder design, bottom = preserve the current layout. Example for coding: left = simplify, right = improve robustness, top = explore broader redesign, bottom = reduce scope. If an action is ambiguous or materially changes a constraint, display a clarification rather than silently guessing. Swipe, click and keyboard navigation call the same deterministic `apply_steering(question_id, action_id)` operation.

### 16.4 Multimodal pipeline

1. Validate file type, size and user consent; store the original locally or in the explicitly configured temporary upload store.
2. Call SAM 3.1 only when grounded object/region selection materially improves the task. Preserve returned masks/boxes and labels as `visual_evidence`, not policy.
3. Pass only the necessary image/reference and structured task context to Muse Spark. Ask for schema-constrained output.
4. Validate generated options against task constraints, supported action types and safety policy.
5. Call Muse Image only when a preview is useful. Store `generated_preview=true`, prompt lineage and source asset references. Do not treat generated imagery as factual evidence.
6. Render one primary question card with image/preview and four labeled edge actions. Keep history, evidence and detailed settings behind secondary interactions.
7. On a user gesture, append a `steering_event`, apply the bounded parameter delta, continue the agent, and record the rule versions and outcomes. Do not treat a gesture as an execution authorization for irreversible actions.

### 16.5 Model adapters

Define interfaces `ReasoningAdapter.generate_decision(context)`, `SegmentationAdapter.segment(image_ref, text_prompt)`, and `ImageAdapter.generate_or_edit(prompt, reference_images)`. Adapter implementations own authentication, request shaping, timeout, retries, model ID, usage/cost logging and response normalization. Model IDs and endpoint paths must come from current official docs and environment configuration, not hard-coded assumptions scattered through business logic. Feature flags permit SAM/Image calls to be disabled independently.

### 16.6 Example event additions

- `visual_asset_attached`: records local asset reference, consent and retention policy.
- `visual_evidence_created`: records SAM model/version, prompt, labels and mask/box metadata.
- `decision_card_rendered`: records question ID and action IDs/edge labels shown.
- `steering_event`: records action ID, edge, gesture type, selected parameter delta and resulting agent continuation.
- `generated_preview_created`: records Muse Image model/version, prompt lineage, source refs and generated-preview label.
- `preference_corrected`: references the superseded rule and the new scope.

### 16.7 Tests and acceptance

- Contract test: every question has one primary question and four visible contextual actions, unless a safety policy deliberately removes/locks an action with a visible reason.
- Grounding test: user selects a named object; SAM result maps to a stable visual evidence ID; the agent refers to that object, not an invented neighbor.
- Visual honesty test: generated preview is labeled as generated and never displayed as a verified real-world listing or measurement.
- Steering test: pointer, swipe and keyboard trigger identical action semantics.
- Scope test: a preference learned in one domain is not reused in an unrelated domain without evidence.
- Safety test: no directional gesture can directly authorize a purchase, send, deletion or other locked action.
- Failure test: API timeout or malformed output leaves the question unresolved and offers retry/clarification; it never silently applies a default action.
- Demo replay: capture baseline versus Switchboard on task completion, steering interactions, preference reuse, correction recovery, model latency and cost.
