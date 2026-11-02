# Adaptive Policy Evolution: Architecture and Delivery Plan

**Status:** implementation plan; first instrumentation slice in progress
**Scope:** backend policy, learning, evaluation, and operational boundaries
**Decision:** let AI and outcome evidence adapt operational policies; keep a small integrity kernel that models cannot edit.

## 1. Product direction

Switchboard should adapt how much autonomy it grants for a particular situation. A user preference that is safe to reuse for a reversible, familiar choice should not be governed forever by a broad static category setting. At the same time, a model must not be able to authorize its own proposal, widen its own authority, or erase a user's revocation.

The target is **adaptive policy content with deterministic policy execution**:

1. Models and learners propose versioned policy changes from eligible evidence.
2. A validator checks structure, provenance, scope, expiry, and integrity constraints.
3. A stable runtime interpreter evaluates the active policy against each request.
4. Every evaluation records which policy version and contextual features led to the result.
5. Outcomes are evaluated against a baseline before a policy is promoted or rolled back.

This is not an unrestricted self-modifying agent. It is a measured control loop whose policy can evolve by context and evidence.

## 2. Current backend map

The implementation is a Python modular monolith with SQLite persistence:

```text
REST / MCP / remote hub
        │
        ▼
QuestionRequest validation and idempotency
        │
        ├── risk classification (config/category/context checks)
        ├── active user-rule lookup and scope checks
        ├── T0 exact → T1 local similarity → optional hosted T3 candidate selection
        └── category stage + risk gate → answer, warn, suggest, shadow, defer
                 │
                 ▼
       SQLite questions / decisions / receipts / events
                 │
                 ├── human feedback, rule correction, revocation
                 ├── agent-reported usage/outcomes (unverified evidence)
                 └── synthetic replay/canary evaluation
```

The service and API layer currently own much of the orchestration. Category stage and locked categories are static/configured inputs; `risk_estimate` is category-level and based on a limited set of confirmed labels. The matcher similarity score is not a probability. Hosted models select from candidate rules but do not provide calibrated confidence. Current replay is useful for regressions, but synthetic cases do not prove a live user benefit.

## 3. What adapts and what stays invariant

### Adaptive operational policy

Policy may vary with verified context, user preference, reversibility, scope, evidence quality, uncertainty, prior corrections, and observed outcomes. Examples include:

- whether to answer directly, show a suggestion, or ask;
- how much evidence is required for a rule in a context;
- whether a rule's scope should narrow after a correction;
- which preference epoch or rule version applies;
- whether an autonomy grant is warranted and for how long;
- when a policy should enter shadow mode, canary, promotion, freeze, or rollback.

These are policy decisions to measure and adapt. A broad category label should not permanently decide behavior when more specific, trustworthy situation evidence is available.

### Integrity kernel

Keep these properties independent of model output and learned reward:

- authenticated identity and workspace ownership;
- an agent cannot expand its own scopes or assert human confirmation;
- explicit user revocation and expiry take effect immediately;
- provenance and audit history cannot be rewritten by a model;
- malformed inputs, stale versions, missing mandatory scope, and component failures fail closed;
- model-generated policy is a proposal until validated and activated;
- no policy can silently convert a preference answer into execution authority.

This kernel is intentionally small. It protects control of the system rather than hard-coding every operational answer by category.

## 4. Target component boundaries

| Component | Responsibility | Change from today |
|---|---|---|
| Ingress adapters | Authenticate caller, validate schema, normalize request | Keep REST/MCP/remote as thin adapters to one request contract |
| Policy registry | Store immutable policy versions, status, parent version, scope, validity, evidence and author | Add versioned policy objects beyond category stage and preference rules |
| Policy interpreter | Deterministically evaluate a policy snapshot and return an explainable result | Separate evaluation from model calls and service orchestration |
| Candidate proposer | Use model/learner to propose structured policy diffs | Models never mutate active policy directly |
| Evidence ledger | Preserve source class, actor, timestamp, verification, and eligibility | Distinguish human labels, tool evidence, agent assertion, model inference, and synthetic data |
| Outcome evaluator | Attribute correction, override, revocation, verified result, and deferral to the decision | Replace aggregate-only assessment with context-aware cohorts and uncertainty intervals |
| Promotion controller | Shadow, compare, canary, promote, freeze, and roll back policy versions | Promotion requires metric evidence and integrity checks |
| Observability | Emit privacy-minimized traces and aggregate policy metrics | Begin with the decision trace added in this change |
| Storage boundary | Keep the modular monolith and SQLite until observed load requires change | Add workspace identity before multi-user release; defer service splitting |

## 5. Policy object and decision contract

The next schema should represent a policy as an immutable, versioned object with:

- stable policy ID and monotonically increasing version;
- target workspace, agent/harness, task class, intent, and context predicates;
- allowed response modes and autonomy ceiling;
- required evidence, uncertainty tolerance, and review behavior;
- validity start, expiry, and revocation state;
- parent version and human-readable rationale;
- source evidence IDs, proposer/model/version, validator result, and promotion record;
- evaluation cohort and baseline metrics.

The runtime interpreter should return a typed decision containing selected policy version, matched conditions, unmet conditions, allowed response mode, and reason codes. Do not expose chain-of-thought. The user-facing explanation should summarize the recorded factors.

Policy conflicts resolve conservatively: prefer narrower scope, lower autonomy, fresher user-confirmed preference, and explicit revocation. If two eligible policies conflict or necessary context is missing, request human input.

## 6. Learning and measurement design

### Evidence quality

Maintain separate evidence classes. Human approvals/corrections and verified tool outcomes can support policy learning under a named eligibility rule. Agent-reported success is useful diagnostic evidence but cannot be treated as a gold label. Model-inferred and synthetic examples are never silently merged into real-user evaluation.

### Metrics

Report by policy version and context cohort, not only by category:

- **harmful/incorrect autonomous decisions:** observed and confidence interval;
- **coverage:** eligible requests answered without interruption;
- **interruption burden:** requests deferred or escalated per task;
- **human correction/override rate:** with correction severity and time-to-correction;
- **scope leakage:** decisions that applied outside confirmed scope;
- **revocation and expiry correctness:** stale authority used after invalidation;
- **latency and model/tool cost:** p50/p95, token usage, and failure rate;
- **calibration:** only for predictors trained and evaluated as probabilities; never use a model's self-reported confidence as calibration.

First collect baselines and confidence intervals. Do not invent success thresholds before observing traffic and label density. Promotion should require evidence that safety is non-inferior to the incumbent policy and that the intended usefulness metric improves. Small or shifted cohorts remain in shadow or fall back to the incumbent.

Use offline replay for regressions, then shadow evaluation on live requests, then tightly bounded canaries. Do not deliberately expose users to known-wrong consequential actions. Account for selection bias: only requests that were answered or corrected are observed labels, so naive accuracy on labeled cases is not a valid policy comparison.

## 7. Delivery plan in dependency order

### Phase 0 — Trustworthy decision records (in progress)

- Make idempotency hashes include permission-relevant risk hints and option values.
- Allow caller risk hints only to raise risk; validate accepted values at all ingress points.
- Stop labeling hosted-model self-reported confidence as calibrated.
- Persist a privacy-minimized policy trace: versions, risk reasons, effective stage, matcher tier, selected rule version, scope result, decision mode, and context fingerprint.
- Add migration and regression coverage for new fields.

**Exit:** REST/MCP/remote behavior agrees; decisions have a durable trace; old ledgers migrate additively; no raw context values are copied into the trace.

### Phase 1 — Baseline telemetry and outcome integrity

- Inventory each current decision path and verify its event/receipt linkage.
- Attach subsequent human correction, override, revocation, and verified outcomes to their originating decision and policy version.
- Separate “no complaint” from a confirmed correct outcome.
- Add dashboards/queries for the metrics above and cohort sample sizes/intervals.
- Record latency and model token usage consistently across matcher tiers.

**Exit:** produce a reproducible baseline report from real evidence, with synthetic data visibly separated.

### Phase 2 — Policy registry and pure interpreter

- Introduce immutable `policy`, `policy_version`, and evaluation-trace records (or a compact equivalent after schema review).
- Move category stage/risk settings behind a policy interface without changing their present behavior.
- Preserve existing API responses and receipts while running the interpreter in shadow against the old path.
- Test conflict resolution, expiry, revocation, stale version checks, and missing-context behavior.

**Exit:** shadow results match the current governor for existing fixtures and live observations, except for documented intentional differences.

### Phase 3 — Policy proposal and validation loop

- Let the model propose a structured policy diff from eligible evidence and a bounded context slice.
- Validate schema, scope narrowing/widening, provenance, expiration, conflicts, and integrity-kernel compatibility.
- Store rejected and accepted proposals with reasons; never execute prompt text as policy.
- Keep proposals shadow-only initially.

**Exit:** proposals are reproducible, attributable, reviewable, and cannot grant authority from agent assertions or bypass revocation.

### Phase 4 — Contextual offline evaluation

- Build replay fixtures from de-identified, eligible traces and explicit labels.
- Compare incumbent policy with adaptive candidates, static baselines, and simple heuristics.
- Evaluate by context subgroup and drift period; use uncertainty-aware risk/coverage curves.
- Use conservative contextual learning only where outcomes are supportable; avoid broad generalization from sparse cohorts.

**Exit:** an adaptive candidate demonstrates a measured usefulness win while meeting the predeclared safety non-inferiority bar.

### Phase 5 — Shadow, canary, and bounded autonomous promotion

- Shadow every candidate before it can affect users.
- Start canaries only in reversible, user preference domains with clear rollback and adequate evidence.
- Let the controller promote, freeze, or roll back within the approved autonomy envelope.
- Escalate uncertain, out-of-distribution, high-impact, or conflicting situations to the human based on the situation and evidence, not a blanket category list alone.
- Keep the user able to inspect, limit, and revoke adaptive policies.

**Exit:** demonstrate stable improvements across time and cohorts, with correct rollback/revocation and no integrity regressions.

### Phase 6 — Architecture scaling from measurements

- Keep the system a modular monolith while the control loop is being measured.
- Establish workspace isolation and migrations before public multi-tenant operation.
- Measure SQLite write contention, WAL growth, p95 latency, and model-call bottlenecks.
- Extract a component or change storage only when a measured bottleneck or fault boundary justifies it.

## 8. Work started in this change

The current code change completes the core of Phase 0:

- request identity now changes when an option's permission-relevant `value` or risk hint changes;
- `risk_hint=locked` is accepted through REST, MCP, and remote forwarding and can only escalate the server's risk result;
- hosted candidate selectors no longer claim their generated confidence is calibrated;
- decisions persist a versioned structured policy trace, including baseline/effective stage and a context fingerprint rather than raw context values.

This is instrumentation and trust groundwork. It does **not** yet adapt the active permission policy. Phases 1–5 are required before policy evolution can make live decisions.

## 9. Risks and controls

| Risk | Control |
|---|---|
| Sparse or biased outcome labels create overconfident policy | Show support and intervals; shadow/fallback when evidence is insufficient; don't treat silence as approval |
| Model proposal broadens scope or authority | Validate typed diffs; compare against parent scope; integrity kernel rejects authority escalation unsupported by user evidence |
| Context drift makes a learned policy stale | Version conditions; monitor cohort drift; expire or freeze; re-evaluate after preference changes |
| Aggregate metrics hide a harmful subgroup | Evaluate meaningful context cohorts and minimum sample support; use conservative fallback |
| Adaptive rules become unexplainable | Immutable versions, concise recorded reasons, provenance, inspectable user controls |
| More services add operational failure modes before need exists | Modular monolith first; split only after measured scale/fault-boundary evidence |

## 10. Decision principle

The architecture should remain open to replacing any hypothesis-driven mechanism. Keep a policy mechanism only when live and replay evidence shows it improves useful autonomy without weakening safety, user control, or auditability. Treat the current LLD as a source of hypotheses and contracts, not as proof that every proposed component is the right long-term design.
