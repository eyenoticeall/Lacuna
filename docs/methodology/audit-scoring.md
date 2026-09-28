# Audit findings and score

The v0.1 audit converts named analytical results and declared policies into deterministic findings.
The score is a review index over that evidence, not a probability that a signal will profit.

This page applies only to the frozen v0.1 signal audit. The v0.8 standardized cross-phase profiles
show categorical evidence coverage and source findings but compute no universal score. See
[Standardized cross-phase audit](../reference/standardized-audit.md).

## Evidence flow

Rules receive an immutable `AuditContext`. They first declare applicability:

- `APPLICABLE` — required evidence exists and the rule evaluates it;
- `UNKNOWN` — the question matters, but evidence is absent or does not establish the claim;
- `NOT_APPLICABLE` — the method genuinely does not apply to this study type.

Unexpected rule errors propagate and fail the audit. Lacuna does not convert implementation failures
into successful or merely unknown results.

## Score version 1

Each rule has a positive weight. Credit by finding state is:

| State | Credit |
| --- | ---: |
| `PASS` | 1.0 |
| `WARN` | 0.5 |
| `FAIL` | 0.0 |
| `UNKNOWN` | 0.0 |
| `NOT_APPLICABLE` | excluded |

```text
robustness_score = 100 × earned_weight / applicable_weight
evidence_coverage = assessed_weight / applicable_weight
```

`UNKNOWN` remains applicable, earns no credit, and is excluded from assessed weight. It lowers both
score and coverage. `NOT_APPLICABLE` leaves both numerator and denominator. Category component rows
show earned, possible, and unknown weight before the total is rendered.

The built-in rules, weights, and thresholds are listed in
[Audit engine and reporting](../subsystems/audit-reporting.md#v01-score-policy). Any threshold or
weight change requires an appropriate rule or score version increment.

## Signal-study assembly

`SignalStudy.audit` computes labels, Spearman IC, balanced quantiles, turnover, decay, and an IC
bootstrap interval. An optional `PurgedKFold` result supplies purging evidence.

IC inference uses one pre-declared horizon: the first study horizon, or the
`policies={"inference_horizon": ...}` value, which must name a study horizon. IC rows for different
horizons estimate different quantities and are never pooled. Consecutive IC periods for an
`h`-observation horizon share `h - 1` returns, so the bootstrap keeps only periods whose label
intervals are disjoint (earliest first: a period is kept when its observation time is at or after
every label end of the previously kept period) and resamples them IID. `IC_DEFINED` and
`IC_PERIOD_SUPPORT` read the declared horizon's IC summary, and `BOOTSTRAP_INTERVAL` warns instead of
passing when fewer than 30 disjoint periods remain. The audit records `inference_horizon` and
`ic_inference_sampling="non_overlapping_label_intervals"` as policies and in rule evidence.

Before rule version 2, the audit bootstrapped every `(date, horizon)` IC row as one stationary
series. On a persistent but uninformative signal with 5D and 20D labels, that interval excluded zero
in about a quarter of null simulations. The fixed-seed guard in
`tests/statistical/test_signal_audit_calibration.py` holds the corrected path near nominal size. Declared survivorship and trial-history policies remain caller assertions in v0.1;
they are not independently discovered from raw data.

Transaction-cost evidence is `NOT_APPLICABLE` to a signal-only study because no portfolio or trade
path exists. Price adjustment, delisting, purged validation, survivorship, and trial-history evidence
stay `UNKNOWN` when omitted.

## Interpretation

A high score means the configured rule set found favorable and sufficiently complete evidence. It
does not prove causality, data licensing, point-in-time safety outside supplied evidence, future
performance, capacity, or executable net returns. Always review:

1. failure and warning findings;
2. unknown count and evidence coverage;
3. source analytical tables;
4. method parameters and warnings;
5. assumptions that remain outside v0.1.

JSON is the canonical artifact. Markdown and HTML escape and present stored evidence without
recomputing rules. See [Result schema compatibility](../reference/result-schema.md) for the persisted
format and [Audit engine and reporting](../subsystems/audit-reporting.md) for extension contracts.
