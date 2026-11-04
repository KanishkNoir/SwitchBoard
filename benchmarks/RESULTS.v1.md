# Synthetic benchmark v1 results

Generated from [results.v1.json](results.v1.json). See [method and limits](README.md).

Each arm receives 40 correlated episodes, 220 questions: 160 eligible for reuse and 60 requiring review.

| Arm | Correct automatic reuse / 160 eligible | Wrong automatic decisions / 220 queries | Reviews / 220 queries | Episodes passed / 40 |
|---|---:|---:|---:|---:|
| always_ask | 0 | 0 | 220 | 40 |
| immediate_resume | 135 | 30 | 55 | 30 |
| switchboard | 105 | 15 | 100 | 35 |
| no_scope | 105 | 35 | 80 | 30 |
| no_dependencies | 105 | 15 | 100 | 30 |

Wrong automatic decisions include correct values returned across a must-review boundary.

## Full Switchboard by condition family

| Family | Queries | Correct automatic reuse | Wrong automatic decisions | Reviews | Episodes passed / 5 |
|---|---:|---:|---:|---:|---:|
| correction_dependencies | 45 | 40 | 0 | 5 | 5 |
| evidence_integrity | 30 | 10 | 0 | 20 | 5 |
| hard_locks | 25 | 5 | 0 | 20 | 5 |
| intent_boundaries | 20 | 5 | 0 | 15 | 5 |
| negative_controls | 20 | 5 | 15 | 0 | 0 |
| noisy_correction | 30 | 10 | 0 | 20 | 5 |
| scope_boundaries | 30 | 10 | 0 | 20 | 5 |
| stable_reuse | 20 | 20 | 0 | 0 | 5 |

## Correction impact

| Arm | Found / 15 affected work IDs | False alarms | Correct / 50 ID-status pairs | Unknown-coverage count checks / 10 |
|---|---:|---:|---:|---:|
| always_ask | n/a | n/a | n/a | n/a |
| immediate_resume | 15 | 0 | 50 | 10 |
| switchboard | 15 | 0 | 50 | 10 |
| no_scope | 15 | 0 | 50 | 10 |
| no_dependencies | 0 | 0 | 0 | 0 |

Always-ask has no rule-backed automatic work to invalidate, so impact scoring is not applicable.

Dataset SHA-256: `e1764e913a54e53f787afb2a0ec7972bb3a71370c248df077a0f777d88083767`.

Service source SHA-256: `d4c10b81e0f0b8d4641e1abe2ba8e249fce05ed332457d9eb26401b66d5b907f`.

These are synthetic service tests with local T0/T1 matching and the risk gate in shadow mode. They do not measure native assistant compliance, model reasoning, user time saved, or a production error rate.
