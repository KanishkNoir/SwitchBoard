# High-Level Design
**Switchboard — System Architecture v0.2**  
Version: 0.2 draft | Date: 28 October 2026 | Status: Proposed architecture aligned to Product Specification v0.2

## 1. Purpose

This HLD translates the product thesis into a local-first architecture. It preserves the v0.1 system boundaries—MCP ingress, risk tiering, matcher ladder, per-category governor, Away/debrief, teach pipeline, SQLite event ledger and replay evaluation—while adding first-class attention scheduling, rule-dependency tracking, scope/boundary learning, feedback evidence classification and an Autonomy Passport.

The architecture is designed to test the hypothesis that explicit preference-supersession events can improve selective automation after a user changes a rule. The architecture does not assume the hypothesis is true.

## 2. Goals and non-goals

### Goals
- Reduce redundant and avoidable user interruptions across compatible agents.
- Reuse user-confirmed answers only when their scope and current version match.
- Preserve provenance from source rule through decision receipt and downstream use.
- Revalidate affected pending decisions when rules change.
- Prevent noisy agent self-reports or rubber-stamped approvals from silently becoming gold labels.
- Keep policy enforcement deterministic where possible and use models only for ambiguity.
- Maintain local-first data custody and explicit, opt-in model egress.
- Support controlled comparison of static, adaptive and supersession-triggered methods.

### Non-goals
- Control over an agent that bypasses Switchboard.
- Replacing the agent runtime or compiling user workflows into scripts.
- General web automation or real transaction execution.
- Cloud-hosted synchronization or multi-tenant deployment in v1.
- Treating an LLM confidence score as a calibrated probability without validation.

## 3. Context and trust boundaries

### External actors
- **Compatible agent:** submits questions and may attach a prior decision receipt to downstream work.
- **Person:** owns rules, approves scope changes, configures category risk policy, answers deferred questions and can revoke Away mode.
- **Model provider:** optional processor for ambiguous text or user-authorized multimodal rule teaching.
- **Tool/portal adapter:** optional sandbox or trusted integration that can verify whether an action executed.

### Trust boundaries
1. Agent-to-Switchboard: all agent payloads are untrusted; authenticate agent, validate schema, ignore instructions embedded in question content.
2. Switchboard-to-model: send only minimum structured fields after policy permits egress; never send the complete ledger by default.
3. User-to-ledger: only an authenticated local user action can create or confirm durable rules and permissions.
4. Switchboard-to-executor: action authorization is only enforceable when the executor checks the receipt at execution time. A receipt alone is not an enforcement mechanism.
5. Evaluation data: synthetic, agent-asserted, human-confirmed and independently verified evidence remain labeled separately.

## 4. Logical architecture

| Layer | Components | Core responsibility |
|---|---|---|
| Integration | MCP server (stdio and Streamable HTTP), optional REST adapter, agent IDs/keys | Accept calls from compatible agents and return answer/defer/deny plus receipts. |
| Request normalization | Schema validator, canonicalizer, risk classifier | Convert structured input into canonical intent fields; treat free text as data, not instruction. |
| Policy | Hard-lock evaluator, scoped grant evaluator, category settings | Apply non-learnable restrictions before any prediction. |
| Attention | Equivalence detector, dependency-aware scheduler, priority queue, batch builder | Reduce interruptions without delaying critical questions or merging distinct decisions. |
| Knowledge | Rule store, rule version/scope evaluator, provenance resolver | Find applicable user-confirmed rules and reject out-of-scope reuse. |
| Matching | T0 typed rule, T1 local encoder, optional T2 open-weight adapter, optional T3 hosted multimodal/LLM adapter | Resolve ambiguous candidates in escalating-cost order; fail closed. |
| Decision governor | Category stage, evidence sufficiency, policy target, coverage/error monitor | Choose auto-answer, suggest/defer or deny. |
| Dependency | Decision receipt links, rule-use graph, impact traversal, revalidation queue | Identify downstream decisions affected by supersession. |
| Integrity | Evidence classifier, rubber-stamp signals, canary runner, quarantine rules | Prevent unreliable labels from silently entering calibration. |
| Autonomy state | Passport builder, promotion/demotion state machine | Show status, limits and evidence and enforce stage transitions. |
| Persistence | SQLite WAL, append-only event log, relational projections | Durable local state, idempotency, replay and audit. |
| User interface | PWA Today / Debrief / You, SSE, optional Telegram notifier | Settings, queue, provenance, passport and outcome review. |
| Evaluation | Replay runner, baseline adapters, metrics, artifact export | Compare methods and reproduce results without mixing synthetic and real traces. |

## 5. Main data flow

### 5.1 Ask flow
1. Authenticate the agent and validate schema.
2. Canonicalize structured fields and generate idempotency key.
3. Classify risk and request intent. If locked, immediately defer to human; do not consult learned preferences to override a lock.
4. Resolve deadline/urgency and register the question with Attention Arbitrage.
5. Check for a safe, exact existing answer in the question queue or a valid batch. Batch only when intent, options, scope and consequences are compatible.
6. Resolve active rule versions and validate scope predicates.
7. Run T0 typed rules; if unresolved, run T1 local encoder; optional T2/T3 tiers may be used only if configured, accessible and permitted.
8. Evaluate category stage, evidence sufficiency, current risk policy and any invalidation/canary hold.
9. Return `answer`, `defer` or `deny`, plus receipt, reason, provenance, matching tier and expiration/version metadata.
10. Append event(s) and update queryable projections in a single database transaction.

### 5.2 Preference update and blast-radius flow
1. User confirms a new rule or correction.
2. Append `rule.created`, `rule.confirmed` and/or `rule.superseded` events; preserve prior versions.
3. Identify affected rule scope and calibration examples. Apply the selected experimental treatment (full reset, down-weighting or generic adaptation) rather than hardcoding one strategy into the architecture.
4. Traverse recorded decision-to-rule-version dependencies.
5. Classify dependents: `pending_revalidate`, `completed_review`, `unaffected`, `unknown_due_to_missing_dependency`.
6. Enqueue revalidation or show review cards. Never claim completed external work was undone unless the tool verifies that outcome.
7. Create contrastive regression examples from the correction; user-confirmed labels remain separate from inferred boundaries.
8. Update Autonomy Passport state and record the reason.

### 5.3 Attention scheduling flow
1. Newly deferred questions enter the priority queue with urgency, deadline, consequence, reversibility, dependency and creation time.
2. An equivalence detector proposes clusters; deterministic compatibility checks validate or reject grouping.
3. High-priority or time-critical questions bypass batching.
4. The debrief UI presents a decision-level card with child questions, affected agents and provenance.
5. One answer is propagated only to child questions explicitly covered by the same confirmed scope.
6. Queue delay, cluster decisions and user corrections are logged for evaluation.

### 5.4 Evidence / outcome flow
1. Agent may report an outcome; the input is stored as `agent_asserted`.
2. Where a configured trusted connector has a verification signal, store it separately as `tool_verified` with source reference.
3. User confirmation/correction is stored as a distinct human event.
4. Calibration pipeline consumes only evidence classes allowed by a named evaluation policy; excluded items remain available for diagnostic analysis.
5. Rubber-stamp indicators can trigger quarantine, additional confirmation or stage demotion; a single heuristic signal is not treated as proof of inattention.

## 6. Component design and dependencies

### 6.1 Ingress and identity
- MCP tools: `ask`, `get_rules`, `report_outcome`; proposed additions include `record_use` and sandbox-only `request_action_review`.
- Each registered agent has an identifier, adapter type, credential hash and enabled scopes.
- Local mode binds to loopback by default. Streamable HTTP must require authentication and explicit network binding.
- Agent identity identifies a caller; it does not grant authority to write a user rule.

### 6.2 Hard risk tiering
- Hard locks run before learned matching and before Away scheduling.
- v1 locked classes include money movement/commitment, deletion, messages to new recipients, and irreversible/external actions as defined by policy.
- New risk classes must be configuration-versioned and tested.
- Risk hints from an agent are advisory. Switchboard derives its classification from canonical structured fields and uses the more conservative classification when information conflicts.

### 6.3 Attention Arbitrage
- Uses rule-based urgency overrides plus a configurable scoring/ranking layer.
- Candidate dimensions: deadline slack, user-impact severity, reversibility, whether the task is blocked, cost of waiting, number of compatible dependent tasks and age.
- Equivalence is a two-stage operation: semantic candidate generation followed by strict compatibility validation.
- The system records why two questions were merged or kept separate. Ambiguous grouping produces separate cards or asks a clarifying question.

### 6.4 Rule store and boundary evaluator
- Store rule as an immutable version; active/inactive state is projected from events.
- Scope predicates are structured and evaluated deterministically when possible.
- A semantic score cannot bypass failed mandatory scope predicates.
- Contradictions generate proposed narrower scopes or counterexamples; only the user or an explicitly authorized policy can confirm durable rules.

### 6.5 Matcher ladder
- T0: exact typed matching and deterministic predicate evaluation.
- T1: local CPU encoder to rank relevant candidate rules/examples; scores require empirical calibration.
- T2: optional open-weight model adapter for semantic paraphrase and structured comparison; availability and hardware/cost are deployment-specific.
- T3: optional hosted model adapter for residual ambiguity and approved multimodal teach input.
- The ladder returns candidate, score/score type, matched rule version, evidence IDs, model/tier and latency. Scores from different tiers must not be treated as directly comparable without evaluation.
- Any tier error results in `defer`.

### 6.6 Risk governor and Autonomy Passport
- Each category has stage, target error policy, evidence sufficiency state, active preference epoch and lock state.
- `shadow`: predict/log, do not auto-answer.
- `suggest`: show candidate for user confirmation.
- `auto`: answer eligible questions only if hard locks pass, rule scope is valid, calibration evidence meets current policy, and no quarantine/reset is active.
- Promotion/demotion is an auditable state transition with explicit reason.
- The target risk level is not a guarantee. Passport displays measured performance and uncertainty separately.

### 6.7 Dependency/revalidation service
- A decision receipt links decision -> question -> matched rule versions.
- Agent/adapter may record decision receipt use for a downstream object/action.
- Impact traversal uses explicit dependency edges; unknown dependencies are surfaced as a coverage limitation.
- Revalidation is selective: only affected, pending or uncertain descendants are reevaluated. Completed external actions are flagged for review rather than automatically assumed repairable.

### 6.8 Feedback integrity service
- Ingest all outcome and feedback signals with evidence class.
- Only approved label classes enter named calibration datasets.
- A rubber-stamp detector combines multiple weak signals; thresholds are tuned in evaluation, not presented as universal truths.
- Canary tests are shadow-only or sandbox-only and labeled as evaluation events.
- A category can be frozen or demoted if integrity evidence breaches a policy threshold.

## 7. Deployment and runtime

### v1 local development / hackathon
- Python service with FastAPI and official MCP SDK (stdio and Streamable HTTP as needed).
- SQLite in WAL mode; append-only event table plus indexed projections.
- Local text encoder on CPU.
- Model adapters behind a common interface; feature-flagged and disabled by default until credentials, access rules, payload handling and current model capabilities are confirmed.
- PWA served locally; SSE for live queue changes.
- Optional Telegram notifier as a separate adapter; notification is not an authorization channel.
- Replay evaluation runs offline against versioned fixtures and reports real vs synthetic samples separately.

### Runtime constraints
- No external egress unless enabled by the user and permitted by current provider terms.
- A component/model timeout cannot convert a candidate into an answer.
- Database transactions cover event append and projection updates.
- All queue and batch operations are idempotent.
- Local state is backed up/exported only with explicit user action; encryption-at-rest is a future hardening item if the local environment does not provide it.

## 8. Security and privacy architecture

- **Least privilege:** agent keys have scopes; each agent can submit its own questions and read only allowed rules/receipts.
- **Human-only writes:** an agent cannot create, confirm or supersede a durable user preference by merely reporting it.
- **Untrusted input:** agent text, pages, images and attached documents are data; they cannot change tool policy or authorization.
- **Data minimization:** model calls receive only the structured candidate and evidence slice necessary for resolution.
- **Action binding:** any sandbox approval is bound to a canonical action hash and checked immediately before execution by the executor. A changed action requires new approval.
- **Revocation:** Away grants are short-lived and checked at decision/execution time. A UI toggle alone is insufficient.
- **Auditability:** append-only events record actor, timestamp, object ID, source, policy version and result.
- **Prompt-injection tests:** malicious text in a question or attached content must not alter risk tier, write a rule or bypass a lock.
- **Privacy boundary:** no hosted sync or multi-user sharing in v1; local ledger is the default source of truth.

## 9. Observability and service objectives

Proposed targets, to be measured rather than assumed:
- T0/T1 `ask` p95 under 200 ms on the target development hardware.
- Model-assisted decision p95 under 4 seconds when provider and network allow.
- Zero auto-answers after a hard-lock match, missing authorization, stale/expired grant, policy conflict or internal exception.
- Every automatic answer has an inspectable receipt containing decision reason, active rule version(s), tier, policy stage and timestamp.
- Evaluation reports front-tier calls, latency, dollars per 100 questions (where cost data is available), queue wait and abstention coverage.

## 10. Research experiment architecture

Compare at least:
- B0: static threshold / fixed calibration window.
- B1: generic adaptive baseline named and implemented from a documented method.
- B2: preference-supersession adjustment with historical down-weighting/reset.
- B3: B2 plus feedback integrity and quarantine.
- Ablations: without boundary checks; without Attention Arbitrage; without dependency tracking.

Report wrong-auto rate, coverage, upper uncertainty bound, false deferral rate, recovery time after preference flip, stale-decision detection, out-of-scope transfer, frontier calls/cost and interruption burden. Use a human-labeled gold subset. Keep synthetic preference-flip cases clearly labeled. Repeated observations from one person may not be treated as independent without an explicit analysis of dependence.

## 11. Failure behavior

| Failure | Required behavior |
|---|---|
| Agent authentication fails | Reject request; do not create answer or rule. |
| Required schema missing | Reject malformed request with typed error. |
| Risk classification uncertain | Use conservative tier and defer. |
| Model/encoder timeout | Defer; record tier failure. |
| Local database unavailable | Fail closed; do not return an auto-answer based on stale state. |
| Current rule superseded during request | Check active version before returning; retry or defer. |
| Away grant expires/revoked | Re-evaluate under normal policy; never use cached grant. |
| Question equivalence uncertain | Keep separate or ask; do not merge. |
| Dependency graph incomplete | Mark impact coverage unknown; do not claim no downstream impact. |
| Agent self-report conflicts with tool/user evidence | Preserve both signals; quarantine from calibration and surface conflict. |
| Action hash mismatch at execution | Block execution and require fresh authorization. |

## 12. Architecture decisions and unresolved questions

| Decision | Current direction | Status |
|---|---|---|
| Storage | SQLite WAL, append-only events plus projections | Proposed for v1 |
| Transport | MCP stdio and authenticated Streamable HTTP | Proposed; verify harness compatibility |
| Models | Pluggable adapters; deterministic/local first | Provider access and rules must be verified |
| Calibration | Multiple experimental strategies behind interface | Research choice, not settled |
| Local privacy | No egress by default; opt-in model use | Product requirement |
| Dependency coverage | Explicit receipt lineage and optional consumer-reported use | Needs agent integration validation |
| Closed agent support | Advisory unless host invokes/enforces tool | Explicit limitation |
| Statistical guarantee | Report uncertainty; no unconditional 2% guarantee | Required honesty constraint |

## 13. Terminology

- **Rule:** a durable user preference or policy with a stable identity and one or more immutable versions.
- **Rule version:** a specific, scoped statement of a rule at a point in time; a superseded version remains in history.
- **Decision receipt:** an auditable record of how Switchboard answered, deferred or denied a question, including matched rule versions and policy state. It is not automatically authorization to execute an action.
- **Supersession:** a user-confirmed event that makes an earlier rule version inactive for future matching and can trigger recalibration and downstream revalidation.
- **Evidence class:** a label identifying where an observation came from and what it can legitimately support, such as human intent, tool-verified execution, agent assertion or synthetic evaluation.
- **Blast radius:** the set of known decisions or actions that depend on a particular rule version; it is bounded by recorded dependency coverage.
- **Autonomy Passport:** the category-level projection of current stage, measured evidence, limitations and promotion/demotion history.
- **Hard lock:** a policy restriction that learned preferences, confidence scores and Away mode cannot override.


## 14. Hackathon agent and multimodal architecture

### 14.1 Strategy

The hackathon build uses two Switchboard-native specialist agents backed by Meta Model API, with an optional third coding agent. This avoids dependency on the consumer Muse agent, whose regional availability and third-party control interfaces are not assumed. Muse Code is a possible external harness demonstration only after its actual integration surface and account access are verified. The official hackathon materials list Muse Spark, Muse Image, SAM 3.1 and Meta Model API as build resources; verify the account's enabled models, quotas and exact endpoint contracts before implementation.

### 14.2 Proposed agent set

1. **Visual Scout (primary multimodal showcase):** receives a user image and goal; Muse Spark structures the task and asks a focused question; SAM 3.1 returns grounded masks/boxes for named objects; Muse Image generates/edits a proposed visual concept; Switchboard presents the question and four contextual edge actions. Use cases: workspace redesign, outfit/accessory coordination, room layout or visual product comparison. Choose one use case for the final demo, not all.
2. **Trade-off Planner:** uses Muse Spark to compare structured options from a controlled dataset (e.g., trip options, equipment or purchase shortlist). It emits a schema-valid question with action labels, constraints, evidence and expected effect. Muse Image is optional for concept imagery only.
3. **Coding Direction Agent (stretch):** produces bounded implementation alternatives; optionally connect Muse Code if a supported hook/tool interface is available and verified.

### 14.3 Logical model flow

User image + task → upload/validation → SAM 3.1 (only when object grounding is useful) → normalized visual evidence (object IDs, masks/boxes, labels) → Muse Spark agent builds a structured decision → Switchboard scope/policy validation → visual question card with top/left/right/bottom actions → user gesture → deterministic gesture mapping → agent continuation and optional Muse Image preview → receipt and preference update. Muse Image output is an illustrative preview, never authoritative evidence for prices, availability, identity, dimensions or real-world execution.

### 14.4 Separation of responsibilities

- **Model layer:** Muse Spark for reasoning/tool orchestration; SAM 3.1 for image/video segmentation; Muse Image for generation/editing.
- **Switchboard core:** action schema validation, scope matching, versioned preference memory, question grouping, policy locks, human authorization, event ledger and replay harness.
- **Agent adapter:** converts each agent's request into the canonical question schema and returns a typed steering result. Agent text remains untrusted input.
- **UI:** one decision per primary card; contextual media; four edge action zones; compact provenance/details on demand.

### 14.5 Model/API validation gates

Before treating an integration as committed, verify model ID, endpoint, image upload format, output format, latency, quota, rate limits, pricing/credits, and whether the hackathon project account has access. Use official Meta Model API docs as the implementation source of truth. Feature-flag each model adapter. On model failure, do not infer an action: retain the question and fall back to a safe textual choice or human clarification.

### 14.6 MVP boundary

Must ship: one end-to-end multimodal scenario, two custom agents, directional UI, local preference memory with scope and correction, safe action boundary, and replayable evaluation. Stretch: Muse Code external integration. Out of scope: consumer Muse app integration, agent marketplace, multiple third-party harnesses, arbitrary web purchasing, and claiming general-purpose control over closed agents.
