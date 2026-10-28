# Product Specification
**Switchboard — Your agents learn when to ask**  
Version: 0.2 draft | Date: 28 October 2026 | Status: Working product specification

## 1. Executive summary

Switchboard is a local-first personal autonomy layer for compatible AI agents. It reduces unnecessary human interruptions by reusing confirmed answers where the context is valid, routing genuinely important decisions to the person, and learning cautiously from corrections and outcomes. It is not another agent, general-purpose memory store, or universal approval gateway.

The product thesis is that the scarce resource in a multi-agent workflow is not only compute or context; it is the person's attention. Individual agents can each behave reasonably and still create a poor overall experience: they ask the same question in different words, apply an old preference outside its scope, miss the downstream effect of a correction, and learn from feedback that is not actually reliable.

Switchboard's proposed differentiation is the closed loop across five capabilities:

1. **Attention Arbitrage:** batch, prioritize and resolve questions so the person handles the fewest necessary interruptions without unsafe delay.
2. **Preference Blast Radius:** track which decisions relied on a rule version and identify downstream decisions that may be stale after a correction.
3. **Boundary Learning:** represent where a preference applies and where it does not; learn from contrastive examples without overgeneralizing.
4. **Outcome Integrity:** distinguish human intent, verified execution, agent self-report and model inference so unreliable evidence does not silently train the system.
5. **Autonomy Passport:** make each category's current automation stage, evidence, limitations and restrictions legible and reversible.

The existing v0.1 research hypothesis is retained: **after a user preference changes, supersession-triggered recalibration may preserve the chosen error policy with fewer interruptions or violations than static and generic adaptive baselines.** This is an unvalidated hypothesis, not a product guarantee or novelty claim.

## 2. Product principles

- **Memory is invisible; consequences are visible.** Users should not have to curate a knowledge graph. They should see why a question was resolved, why the system deferred, and what a correction affects.
- **Ask less, not blindly less.** A lower interruption count is only positive when wrong answers, missed high-impact questions and user effort do not worsen.
- **Scope before similarity.** A semantically similar question is not necessarily governed by the same rule.
- **Human intent is not an agent assertion.** An agent's claim of success is telemetry, not ground truth.
- **Safe by default.** On uncertainty, policy conflict, missing evidence or component failure, defer rather than guess.
- **Local-first and user-owned.** The answer ledger is stored locally. External model calls are opt-in and minimized to necessary structured content.
- **Composable, not coercive.** Switchboard works when compatible agents call it. It does not claim to control closed agents that bypass its interfaces.
- **Evidence before autonomy.** Each category remains in Shadow or Suggest until the available evidence supports a cautious promotion policy.

## 3. Problem and target users

### 3.1 Primary problem

People who use several AI agents are repeatedly asked for preferences, permissions and disambiguations. Existing agents hold local context and approval decisions, but context and decisions often do not transfer across agents. Users must mediate between agents, repeat explanations, inspect actions and correct stale assumptions.

### 3.2 Initial target segment

The initial segment is technically capable individual users who run multiple compatible agents or agentic developer tools, including local or CLI-based agents, and are willing to install a local MCP server. This is a beachhead segment, not a claim that all consumers are ready to configure agent infrastructure.

### 3.3 Jobs to be done

- When several agents ask overlapping questions, help me make the underlying decision once rather than respond to each agent separately.
- When I correct a preference, help me understand which previous decisions and pending actions might now be wrong.
- When a rule is relevant only in specific contexts, do not apply it elsewhere just because the words look similar.
- When a category becomes more automated, show what evidence supports that decision and what remains restricted.
- When something goes wrong, let me trace the rule, evidence and decision that led to it.

### 3.4 Non-goals

- Replacing Claude, Codex, OpenClaw, Hermes or other agents.
- Compiling observed workflows into deterministic scripts or skills.
- General-purpose long-term memory or a searchable personal knowledge base.
- A universal human approval inbox as the sole product proposition.
- Executing real payments, irreversible external actions, or autonomous actions on arbitrary third-party websites in v1.
- Forcing closed agents such as products that do not expose a compatible integration to use Switchboard. Any such integration is advisory unless the host cooperates.
- Hosted multi-user synchronization in the initial local-first release.
- Claiming a statistical error ceiling has been guaranteed from a small sample.

## 4. Positioning and product promise

**Positioning:** Switchboard is a personal autonomy controller for compatible agents. It helps them reuse confirmed answers, understand their scope, coordinate interruptions and react safely when user intent changes.

**User-facing promise:** “Your agents learn when to ask.”

**Proof required:** In a replay and multi-agent pilot, Switchboard should reduce unnecessary human-facing questions while maintaining or improving wrong-auto rate, critical-question recall, downstream consistency and user effort relative to baselines.

**What Switchboard is not claiming:** It does not guarantee that an AI will never be wrong, that every agent will integrate, or that a 2% configured policy means the next answer has a 2% probability of being wrong. The configured risk level is a target for an evaluation policy; evidence sufficiency and statistical uncertainty must be shown separately.

## 5. Feature specification

### 5.1 Attention Arbitrage

**Purpose:** minimize the user's total attention burden, not simply the number of cards in an inbox.

**Behavior:**
- Accept structured questions from authenticated compatible agents.
- Determine whether the question is already answered by a valid rule, represents an equivalent open question, depends on another question, or requires immediate attention.
- Merge only questions that share the same decision intent and have compatible options and consequences. Similar language alone is insufficient.
- Prioritize by urgency, consequence, reversibility, deadline, dependency and the cost of waiting.
- Briefly defer low-urgency questions to a batch window when doing so is safe.
- Never delay a question classified as locked, safety-critical, time-critical or legally/financially consequential merely to improve batching.
- Show consolidated options with the agents and decisions affected, and retain the provenance of every original question.
- When an answer resolves several questions, record exactly which questions and rule scopes it covers.

**Acceptance criteria:** duplicate interruptions decrease on the benchmark; critical questions are not missed or delayed past their deadline; distinct decisions are not collapsed into one; every grouped question remains traceable.

### 5.2 Preference Blast Radius

**Purpose:** detect downstream decisions that relied on a superseded rule.

**Behavior:**
- Every reusable answer has a versioned rule identifier.
- Every answer receipt records the rule versions and source evidence used.
- A compatible agent can associate subsequent decisions or sandbox actions with the receipt that influenced them.
- When a rule is corrected or superseded, traverse recorded dependencies and classify affected work as pending, completed, unaffected, or uncertain.
- Revalidate only affected pending decisions; suggest repair or human review for completed external actions.
- Do not imply that an external action has been recalled or repaired unless there is verifiable evidence.
- Mark dependency coverage when the consumer agent did not provide downstream-use information; absence of a recorded dependency is not proof of no impact.

**Acceptance criteria:** high-impact affected pending decisions are surfaced; unaffected decisions are not needlessly invalidated; provenance remains available after evidence aging or compaction.

### 5.3 Boundary Learning

**Purpose:** prevent a preference from being applied outside its valid scope.

**Behavior:**
- A rule stores explicit context predicates such as category, channel, destination type, task class, date range or user-confirmed qualifier.
- Rule matching proceeds through scope validation, deterministic matching, local semantic matching and optional model-assisted disambiguation.
- A high semantic score cannot override a failed hard scope predicate.
- Corrections can create a counterexample or narrower scope, but inferred boundaries are suggestions until confirmed or supported by policy-approved evidence.
- The system records both positive examples and contrastive negative examples where a similar-looking question must not reuse the rule.
- When scope is ambiguous, defer rather than broaden the rule silently.

**Acceptance criteria:** lower out-of-scope transfer rate than a semantic-only matcher at comparable coverage; improved separation of near-identical in-scope and out-of-scope cases.

### 5.4 Outcome Integrity

**Purpose:** prevent unreliable signals from corrupting calibration and rule quality.

**Evidence classes:**
- `human_confirmed`: the user explicitly confirms the answer or rule.
- `human_corrected`: the user explicitly rejects or changes a prior answer.
- `tool_verified`: a trusted connected tool provides verifiable evidence about execution or state.
- `agent_asserted`: the agent reports a result without independent verification.
- `model_inferred`: a model infers a possible label or outcome.
- `synthetic`: generated evaluation example, never represented as a real user event.

**Behavior:**
- Preserve source, timestamp, confidence/quality metadata and provenance for every feedback item.
- Do not treat `agent_asserted` or `model_inferred` as equivalent to a human-confirmed correctness label.
- Monitor signs of rubber-stamping, including abnormally high approval rates paired with unusually short review times, zero interaction with evidence, reversals and canary failures.
- Treat these signals as suspicion indicators, not proof that a user was inattentive.
- Run canaries in shadow evaluation or sandbox tasks. Never intentionally expose a real user to a known-wrong consequential action as an experiment.
- Quarantine questionable labels from calibration until resolved; retain them for diagnostics.

**Acceptance criteria:** synthetic or agent-asserted labels cannot silently enter the gold set; suspicious feedback can freeze or demote a category; canary behavior is recorded and never treated as ordinary preference evidence.

### 5.5 Autonomy Passport

**Purpose:** make a category's current permission and evidence status understandable.

**Shown fields:** category, current stage (`shadow`, `suggest`, `auto`), allowed question classes, locked classes, active rule version, recent preference change, relevant sample sizes, evidence types, measured coverage/error with uncertainty, latest correction signals, and promotion/demotion reason.

**Behavior:**
- Stage transitions are governed by explicit policy, not by a displayed confidence score alone.
- Insufficient evidence means remain in Shadow or Suggest.
- Preference supersession invalidates or downweights affected historical calibration according to the experiment variant.
- A category can be demoted immediately on a hard safety event, scope violation or verified critical error.
- The interface must state that sample metrics are historical measurements, not guarantees about the next decision.

**Acceptance criteria:** users can explain why a category is in its current stage; the system can produce an audit record for each promotion/demotion; a preference change cannot leave stale automation authorization active without reassessment.

## 6. User experience and core journeys

### 6.1 First-run setup

1. Install the local server and enable one compatible agent integration.
2. Choose local-only mode or explicitly enable permitted model calls.
3. Review default locked categories and set the desired risk target for learnable categories.
4. Import a small, consented history or begin with no backfill.
5. Start in Shadow mode; Switchboard predicts and logs without answering autonomously.
6. Review a summary of historical behavior and decide whether to move a category into Suggest.

### 6.2 A question arrives

1. Authenticate agent and validate schema.
2. Classify action and risk from structured fields; agent-supplied prose cannot override policy.
3. Check hard locks and deadlines.
4. Check current rules and scope boundaries.
5. Resolve by exact typed rule or local matcher when sufficiently supported.
6. Ask an optional model tier only when permitted and necessary.
7. Apply category stage and risk policy.
8. Return an answer with evidence receipt, or defer into a prioritized queue/batch.
9. Record question, decision, matching path, latency and model usage.

### 6.3 User corrects a preference

1. The user edits a rule or rejects a suggestion.
2. Switchboard proposes a scoped replacement and shows the old rule plus the context where it was used.
3. The user confirms, edits or cancels.
4. The ledger appends a supersession event; it does not overwrite history.
5. Affected decisions are found using dependency records.
6. The category is placed into the experiment's reset/recalibration state.
7. Pending affected decisions are revalidated; completed external actions are reported for review when relevant.
8. Regression cases are created from the correction.

### 6.4 Away mode

Away mode is a time-bound, scoped grant, not a global bypass. It has an explicit expiry, included categories, excluded action classes, a clear revoke/pause-all control and enforcement at the decision point. Locked actions remain locked. On expiry or revocation, behavior returns to the configured normal mode. A question can be queued only if waiting is safe.

### 6.5 Debrief

The user sees priority-ordered questions, provenance and why each was grouped or deferred. Responses include answer, deny, clarify, postpone and reasoned correction. Denial reasons are structured as feedback but do not become permanent preferences without adequate context/confirmation. Every decision is reversible within Switchboard's own local state; this does not make external actions reversible.

## 7. Product requirements

| ID | Requirement | Priority | Acceptance summary |
|---|---|---|---|
| PR-01 | MCP ingress | Must | Authenticated compatible agents can submit validated structured questions. |
| PR-02 | Local event ledger | Must | User rules, decisions, provenance and lifecycle events are append-only. |
| PR-03 | Locked risk classes | Must | Money, deletion, new recipients and irreversible actions defer to human in v1. |
| PR-04 | Rule scope validation | Must | Scope is checked before semantic matching. |
| PR-05 | Shadow/Suggest/Auto stages | Must | Each category has an explicit stage and audit trail. |
| PR-06 | Attention scheduler | Should | Safely batch equivalent low-urgency questions and prioritize deadlines. |
| PR-07 | Rule supersession | Must | Corrections version rules and initiate recalibration. |
| PR-08 | Dependency tracking | Should | Decisions reference rule versions; downstream consumers can record use. |
| PR-09 | Feedback evidence classes | Must | Human, tool, agent, model and synthetic evidence remain distinguishable. |
| PR-10 | Autonomy Passport | Should | User can inspect category status and evidence limitations. |
| PR-11 | Teach from voice/image | Should | Model proposes typed rules; user confirms before ledger write. |
| PR-12 | Away grant and revoke | Must | Time-limited scope; never overrides locks; revocation enforced. |
| PR-13 | Replay evaluation | Must | Replays compare proposed method and baselines on labeled traces. |
| PR-14 | Action-bound receipt | Must for sandbox | Approval is bound to canonical action hash and verified at execution boundary. |
| PR-15 | Hold-and-release | Could | Sandbox-only queued actions revalidate before release. |

## 8. Success metrics and guardrails

**Primary outcome metrics**
- Human-facing questions per completed task.
- Median and p95 human interruption latency.
- Decision coverage: eligible questions resolved without human response.
- Wrong-auto rate, with uncertainty intervals and a clearly defined denominator.
- Critical-question recall and number of harmful or late deferrals.
- Downstream stale-decision detection recall after preference supersession.
- Out-of-scope rule transfer rate.

**Efficiency metrics**
- T0/T1 resolution share.
- T2/T3 calls per 100 questions.
- Latency p50/p95 by tier.
- Cost per task and per correctly auto-resolved question.

**Feedback integrity metrics**
- Rate of labels excluded/quarantined by evidence policy.
- Canary detection rate and false-alarm rate in the test harness.
- Disagreement between agent assertion and independent verification.
- Regression cases passed after a rule update.

**Guardrails**
- No increase in locked-action auto-approvals; target is zero.
- No model or encoder failure may default to an automatic answer.
- No synthetic example may be presented as a real user trace.
- No unsupported claim that a small sample proves a strict population error ceiling.
- No user correction silently broadens a rule's scope.

## 9. Market distinction and positioning assumptions

The category already contains memory layers, MCP authorization gateways, approval queues and rollback tools. Therefore, Switchboard should not lead with “an approval inbox,” “shared memory,” “scoped permissions,” or “undo.” Its proposed distinction is the connected behavior: attention scheduling + scope-aware reusable answers + downstream dependency repair + evidence-aware adaptation after a preference change.

This is a product hypothesis, not a verified moat. Public product descriptions and preliminary competitor scanning do not establish absence of comparable implementations. Before making a novelty claim, conduct a focused landscape audit and hands-on tests against the closest products.

## 10. Release scope

### Hackathon MVP
- One local Switchboard instance.
- MCP integration with at least two compatible agent harnesses if feasible.
- SQLite event ledger, rule versioning and structured receipts.
- Shadow/Suggest/Auto stage flow with hard locks.
- Rule scope matching and explicit supersession.
- Simple Attention Arbitrage (deduplicate only well-supported equivalents; priority queue).
- Dependency capture for decisions and sandbox actions.
- Feedback evidence classes and canary evaluation in shadow/sandbox.
- Autonomy Passport view.
- Replay harness with labeled synthetic cases clearly separated from real consented traces.

### Defer unless the core is stable
- Full general-purpose dependency graph across external tools.
- Hosted synchronization or multi-user collaboration.
- Universal closed-agent enforcement.
- Real-world payment, email sending, deletion or irreversible execution.
- Advanced multimodal attachment workflows beyond a small, user-confirmed teach path.
- Production guarantee at a 2% error rate.

## 11. Open questions

- Which question fields can be made consistent across all target agent harnesses?
- What evidence is actually available from model providers for confidence estimation, and can the proposed tiers be used within current access/rules?
- How can equivalence be evaluated without merging semantically adjacent but consequentially different questions?
- How much dependency information will agents reliably provide after consuming an answer?
- Which statistical guarantee, if any, can be supported under sparse, non-independent, user-specific data and preference changes?
- Which parts of the workflow count as new work under the hackathon rules, and which integrations are permitted?


## 12. Hackathon agent strategy: Meta-first, adapter-based

### 12.1 Principle

Switchboard is the interaction and preference-control layer, not a marketplace of agents that must be built before the product works. For the hackathon, use Meta Model API models to build two Switchboard-native specialist agents, and pursue one real external harness integration only if it can be demonstrated reliably. The consumer Meta Muse app is not a dependency; access and integration into third-party control loops are not assumed.

### 12.2 Recommended demo agents

**A. Visual Scout (image + vision + language).** A user supplies a photo of a room, desk, outfit, product, or travel scene. Muse Spark interprets the goal and proposes a small set of choices. SAM 3.1 segments named objects or regions so the user can point to “that lamp”, “the chair”, or “the item on the left” rather than describing it. Muse Image can generate a contextual concept/mock-up or edit a supplied image to preview a proposed change. Switchboard presents one question at a time with the relevant visual and directional actions. Example: “What should change in this workspace?” Left = lower cost, right = more comfort, up = bolder redesign, down = keep more of the existing layout. These meanings are task-specific and explicitly rendered on screen.

**B. Trip / Purchase Trade-off Agent.** Muse Spark builds a constrained shortlist from user-provided options or a controlled demo dataset. Muse Image can create a mood-board/visual preview where useful; it must not fabricate product facts or imply generated imagery is a real listing photo. The user steers cost, comfort, ambition or simplicity. The agent revises the shortlist and explains the changed trade-off. This is a visually legible demo of repeated preference learning.

**C. Coding Direction Agent (stretch).** A small agent backed by Muse Spark proposes alternative implementation plans or reviews a bounded code change. Directional actions alter the plan (simpler, more robust, broader, narrower). If Muse Code is accessible and offers a reliable supported integration, demonstrate it as an external harness; otherwise do not fake a direct Muse Code integration.

### 12.3 Model responsibilities

- **Muse Spark / available Meta LLM:** orchestration, question formulation, option generation, contextual interpretation, structured action proposals, and summarizing why a choice changes the plan. It does not independently grant authorization.
- **SAM 3.1:** grounded object/region selection through masks and boxes from user-provided images/video. It is a perception tool, not a conversational planner and not an image generator.
- **Muse Image:** generates or edits visual previews. Generated visuals are labeled as concepts; factual listings, prices, availability and measurements must come from trusted inputs or be clearly marked unknown.
- **Switchboard deterministic layer:** gesture-to-action mapping, scope checks, preference ledger, policy locks, audit receipts, and explicit confirmation for consequential actions. Do not delegate these invariants to a generative model.

### 12.4 Hackathon scope and demo proof

Required: one complete visual question loop, two working specialist agents (at least one using vision; ideally one SAM + Muse Image loop), durable scoped preference memory, correction/revocation, and replayable evaluation. Stretch: a real Muse Code or other external harness integration. Do not spend the MVP on a marketplace, account federation, live shopping inventory, or an unverified consumer Muse integration.

Acceptance test: select an object in an uploaded image; ask a contextual question; steer with one of four edge actions; see the agent update its recommendation/visual preview; repeat a similar task and observe the relevant preference being reused; change the preference and verify it no longer applies in an unrelated context.

## 13. Directional interaction model

The question and its relevant visual evidence dominate the screen. Four contextual actions are arranged on the top, left, right and bottom edges of the decision card—not as a row of generic arrows below the image. Each edge includes a short action label for the current question. The directions are stable spatial affordances, but their semantic actions are context-dependent and always visible (e.g., “Cheaper”, “More comfort”, “Explore”, “Simplify”). Gestures are shortcuts for steering, not authorization. A swipe may update the plan or select an option; purchases, sends, deletions and other consequential actions require their own explicit authorization. Secondary actions (details, skip, undo/correct) remain visually quiet.
