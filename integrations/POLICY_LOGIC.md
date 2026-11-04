# Rule boundaries, conflicts and recalibration

Switchboard's operator controls live under **Agents & rules**. These changes strengthen deterministic service policy. They do not add native-client enforcement, automatic policy promotion, or a model's authority to grant permission.

## Declare category requirements

Under **Category boundaries**, choose a category and list the context fields each rule must constrain—for example, `project, workspace` for report formatting. Saved rules can contain multiple boundaries and alternative values. Missing request context still causes deferral.

Requirements apply immediately to existing rules as well as new rules and corrections. An incomplete existing rule is marked as paused for automatic reuse; its history and original scope remain intact. Repair it with **Correct this rule**. Switchboard does not invent an omitted boundary or silently widen the saved rule.

Categories without a configured contract retain legacy scope behavior. This is deliberate compatibility, **not evidence that their boundaries are complete**. The operator chooses category requirements; installing the code does not silently rewrite live preferences. Configuring an empty required-field list still requires a bounded rule unless a deliberate global rule is permitted.

Global rules need both category permission and an explicit global flag on the individual rule. Turning on category permission alone does not convert incomplete rules into global rules. Hard locks apply to global rules too.

Operator-authenticated API:

```http
PUT /settings/reports/scope-contract
Content-Type: application/json

{
  "required_fields": ["project", "workspace"],
  "evidence_fields": ["document_kind"],
  "allow_global": false
}
```

`GET /settings/{category}/scope-contract` returns the saved requirements. `PUT` returns any existing rule violations. Changes are transactional, audited and visible across connections. Invalid scopes (misspelled structure, empty values, objects used as scalar boundaries, or conflicting global/mandatory declarations) are rejected. Scope comparisons distinguish JSON booleans, numbers and text.

## Resolve exact-rule overlaps

Exact matching considers every applicable exact rule rather than choosing the first row. Precedence requires logical containment of scope values and compatible predicate constraints. Counting fields, insertion order and a model's confidence are not precedence rules.

- A strictly more specific exact rule can override a broader default.
- Incomparable or equally applicable exact rules with different answers defer with `conflicting_rules`.
- Equivalent answers use a stable version ID as the receipt source.
- A missing field that could reveal a conflicting exact rule blocks fallback, including incomparable rules.
- An explicit exact-question constraint remains a constraint even if keywords are also supplied.

This exact-rule precedence does not elevate a fuzzy or model match above an exact rule. Existing semantic ambiguity handling remains conservative. New conflicts or contract changes during matching are detected again inside the commit transaction; stale matching results defer. The decision trace includes conflict version IDs or missing rule boundaries without raw context values.

Saving an inbox choice for a different scope or intent creates a separate rule. It does not erase another project's preference merely because its keywords are the same. A same-scope, same-intent correction can supersede its existing rule.

## Recalibrate according to the change

| Change | Behavior |
|---|---|
| Identical answer, equivalent predicate and scope | Keep the version, preference epoch and existing hold; audit the unchanged update. |
| Only narrow the scope, with no existing hold | Create a version; keep automation within the remaining boundary. |
| Change an exact rule's answer | Require one fresh confirmation. |
| Change a semantic rule's answer | Require three distinct fresh contexts. |
| Widen/change the boundary or change the predicate | Require at least three distinct fresh contexts. |
| Narrow a rule already on hold | Preserve at least the previous confirmation requirement; narrowing cannot bypass the hold. |

These are explicit policy thresholds, not learned probabilities or production risk guarantees. Only the affected rule is held. Stage settings, category quarantine, the configured risk gate and hard locks continue to apply independently.

Fresh contexts use saved scope fields and operator-declared evidence dimensions. A configured contract defaults to counting its required fields; operators can add relevant scalar dimensions such as `document_kind`. Unconfigured categories use the stable identity fields `account`, `branch`, `env`, `environment`, `project`, `recipient`, `region`, `repo`, `repository`, `team` and `workspace`, plus the rule's mandatory fields. Task IDs, clocks and arbitrary nested metadata do not count by default. Changing a contract resets held confirmation counts because the evidence definition changed. Old hashes of full contexts cannot count toward the new definition.

Agent success claims remain quarantined and cannot release a hold. A user's one-time answer must agree with the held version. The system does not treat agent-provided context as independently verified environmental truth; adapters and users still need to supply accurate context.

When a fixed scope cannot provide enough distinct meaningful contexts, use **Review recalibration**. Read the current answer and boundaries, then deliberately confirm **Confirm boundaries & resume**. This releases only the displayed rule version, never the whole category. It creates an audit event, not fabricated fresh contexts or correctness labels. Incomplete scopes, locked categories and stale versions cannot be resumed this way. Other gates remain active.

## Preview before changing a rule

`POST /rules/{rule_id}/preview` evaluates the proposed answer, predicate and scope against recorded work without writing a version, event or hold. The UI displays the planned confirmation requirement and counts only actionable downstream statuses; unknown coverage is shown separately.

Preview and correction requests support `expected_version_id`. The operator UI sends it, so a stale preview cannot overwrite a newer correction. `POST /rules/{rule_id}/review-hold` requires that version ID and `confirmed: true`. These are operator-authenticated routes; agents receive no new policy-writing tools.

## Evidence

Regression coverage exercises scope contracts, atomic failures, operator authorization, exact-rule conflicts in both insertion orders, list containment, missing-context fallback, unchanged corrections, narrowing/widening, stale previews, metadata farming and explicit rule review. Browser checks use synthetic data for desktop and 390-pixel phone layouts.

The historical benchmark v1 dataset and report remain frozen. [The current policy run](../benchmarks/RESULTS.policy-v2.md) reuses that same dataset, with a new source fingerprint. It includes **five additional reviews** because task-ID changes no longer release semantic holds. These fixtures do not configure category contracts and therefore do not measure the new contract feature's benefit. Actual assistant compliance, correction delivery acknowledgements and decision expiry remain separate work.
