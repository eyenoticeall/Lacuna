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

`SignalStudy.audit` computes labels, Spearman IC, balanced quantiles, turnover, decay, and—when at
least two IC values exist—a stationary bootstrap interval. An optional `PurgedKFold` result supplies
purging evidence. Declared survivorship and trial-history policies remain caller assertions in v0.1;
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
