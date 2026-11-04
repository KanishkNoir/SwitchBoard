# Switchboard synthetic service benchmark

This benchmark asks a narrow question: **when can the decision service reuse a saved preference, when must it ask, and which recorded work needs review after a correction?** It exercises the real service, SQLite ledger, matcher, holds, receipts, dependency records and evidence quarantine. It does not run Claude, Codex, Muse Code or other native assistants.

The [current generated results](RESULTS.policy-v2.md), [full sanitized traces](results.policy-v2.json), [frozen input](scenarios.v1.json) and [runner](../switchboard/benchmark.py) are checked in together. Failures remain in the report. The original [v1 report](RESULTS.v1.md) and [v1 traces](results.v1.json) are preserved as historical measurements at commit `7c4913f`.

## Dataset and protocol

Version 1 contains **40 episodes and 220 questions per arm**: five domains (reports, coding, scheduling, writing and charts) crossed with eight condition families. These are authored, correlated fixtures, not 40 independent users, a representative workload, or a held-out natural-language dataset. Each domain changes the question, category, preference values and workspace; conditions intentionally repeat. The [authoring script](build_dataset.py) expands templates into the frozen JSON; the runner reads that JSON rather than generating expectations at runtime.

The input was frozen before the first full measurement. Expected answers, must-review boundaries and work ID/status expectations are authored independently of the service's output. The original input and output have not been edited for subsequent policy changes. Current results use a new source fingerprint.

| Family | Questions | What it checks |
|---|---:|---|
| Stable reuse | 20 | Two authenticated synthetic agents reuse a preference, including a local paraphrase. |
| Scope boundaries | 30 | A different project/workspace and missing context require review. |
| Intent boundaries | 20 | Preference rules do not authorize permission/disambiguation requests or unseen categories. |
| Correction dependencies | 45 | No-op and changed-answer corrections; pending, completed, failed, unaffected and unknown work; unrelated-rule and unrecorded-use controls. |
| Noisy correction | 30 | An incorrect supplied correction disagrees with the oracle, then is repaired. |
| Hard locks | 25 | Money movement, deletion, new recipients and irreversible action review require a deliberate answer despite a matching rule. |
| Evidence integrity | 30 | 250 agent success claims per arm cannot become calibration labels or advance holds; duplicate contexts cannot satisfy a three-context semantic hold. |
| Negative controls | 20 | Deliberately incomplete authored scope and preference changes never communicated to the service expose failures. |

Each episode/arm starts with an isolated in-memory database and two fresh agent identities. Saved rules model prior user choices; categories are manually set to `auto` except in always-ask. No staged policy promotion or cold-start learning is being measured. The observed risk gate uses its default **shadow** mode, not evidence-enforcing mode. Local T0 keyword/exact matching and T1 token similarity are enabled; T2/T3, Baseten, Modal inference and all other provider access are absent from the injected matcher. Nothing calls the hosted hub or changes real user rules.

All labels are synthetic. To exercise real hold behavior, the isolated fixture calls the operator's `answer_inbox` API, which internally represents a human answer. That is simulation within a disposable database, **not actual human confirmation** or gold evidence for a live user. Every arm has the same authored oracle: whenever it defers, it receives that question's answer through the same API, and the runner checks the answer is retrievable through the agent-owned answer-status API. Automatic answers receive no extra oracle feedback. Explicit corrections arrive at identical steps for every arm.

## Comparisons

- **Always ask:** the real service stays in `shadow`, requiring an oracle answer for every question. This is the zero-reuse reference.
- **Immediate resume:** the same scoped service and corrections, but each recalibration hold is explicitly cleared. This isolates the hold's cost and benefit; it is not a benchmark of a competing memory product.
- **Switchboard:** scoped rules, actual recalibration holds and evidence quarantine remain enabled.
- **No scope:** mandatory scope is actually omitted from created rules. All other behavior is unchanged.
- **No dependencies:** `record_use` calls are actually omitted. Authored work expectations remain identical; impact recall is calculated from the returned rows, never forced to zero.

All arms retain the same hard-lock logic and evidence-integrity implementation. The immediate-resume arm already discards agent claims, so these results do not establish an evidence-integrity advantage over that arm.

## Scoring

**Correct reuse** requires both the authored value and permission to reuse it. A correct value returned across a must-review boundary is a wrong automatic decision. The suite has 160 reusable queries and 60 must-review queries. Reports give counts and denominators for automatic coverage, correct reuse, wrong decisions, boundary violations and review recall. Reviews count initial deferrals; they are simulated interactions, not timed human effort. Retrieving a queued answer does not count as another question. An episode passes only when every returned answer, boundary, evidence invariant and applicable impact check passes.

**Correction impact** matches declared downstream work IDs, not merely a nonempty `affected` list. The five dependency episodes each check a no-op correction and a changed-answer correction. In total there are 15 actionable work IDs, 50 expected ID/status pairs and 10 checks of unknown unrecorded-use counts. `revalidate`, `review_completed` and `review_failed` are positive detections; `unaffected` and `unknown_dependency_coverage` never earn true-positive credit. Wrong IDs produce false alarms and misses. Wrong statuses fail exact pair grading. Unrelated work must not appear. Always-ask has no rule-backed automatic work, so its impact metrics are not applicable.

The source fingerprint hashes sorted `switchboard/**/*.py` relative paths and their file bytes. Dataset and source SHA-256 values, Python/dependency versions, configuration and step-by-step failures accompany the report. No API keys, live content, generated agent IDs or receipts are exported. Hashes can differ after newline conversion; compare logical results when running on another platform. There is no random seed because fixtures and grading are deterministic.

## Findings and limits

On the frozen v1 dataset with the current policy, full Switchboard makes **15 wrong automatic decisions versus 30 with immediate resume**, while requiring **105 reviews versus 55**, out of 220 questions. Always-ask makes zero wrong automatic decisions with 220 reviews. Full Switchboard finds **15/15** affected recorded work IDs with zero false alarms; omitting dependency recording finds **0/15**. Removing scope adds 20 boundary violations.

The historical implementation required 100 reviews and produced 105 correct automatic reuses; the current implementation requires 105 reviews and produces 100 correct automatic reuses. That additional cost is deliberate: v1's evidence-integrity cases vary task IDs, which no longer qualify as distinct meaningful contexts. The fixture family still delivers its answers through simulated review, but automation remains on hold. Category contracts are not configured in this dataset, so it cannot show their benefit. Dedicated [policy regression tests](../tests/test_rule_policy.py) cover those new behaviors. This report does not claim an improved aggregate error score.

All 15 full-service errors occur in the deliberately adverse negative controls: five scope boundary violations caused by incomplete rule authoring and ten stale values after unannounced preference changes. Both scoped automatic arms fail these controls. Holds protect against the supplied noisy corrections here; they cannot invent a missing boundary or discover an unreported preference change. These are product limits, not passing cases excluded from the headline.

Do not infer population error rates, statistical significance, assistant compliance or time saved from these template repeats. We report no confidence intervals. A broader evaluation still needs independently authored tasks, actual native-client execution with observed tool calls, and consented user sessions. [Client support evidence](../integrations/CLIENT_SUPPORT.md) covers separate connection and enforcement checks; it is not native execution evidence for this dataset. The subprocess MCP-over-HTTP integration test checks transport compatibility, not assistant reasoning.

## Reproduce

From the repository root with Python 3.12+ and project dependencies installed:

```powershell
uv run python -m switchboard.benchmark --output .tmp/results-current.json --markdown .tmp/RESULTS-current.md
uv run pytest tests/test_benchmark.py tests/test_evaluation.py tests/test_harness2.py tests/test_stress.py -q
$env:SWITCHBOARD_IT = '1'
uv run pytest -q
```

These output paths preserve both checked-in reports. To reproduce the historical implementation, check out commit `7c4913f` in a separate worktree and run its version of the runner. `build_dataset.py` is for reviewing fixture authorship; it is not needed to run the frozen suite. Changing cases or expectations requires a new dataset version and a fresh full run.

The legacy [replay evaluator](../switchboard/evaluation.py) remains for API compatibility. Its impact scorer now records real work edges and matches affected IDs; its dependency ablation really omits those edges. Every legacy arm now receives the same oracle on deferral. The README uses this versioned benchmark instead of the old 11-question table.
