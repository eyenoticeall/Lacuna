# Bias detection and point-in-time safety

**Status:** point-in-time joins and core leakage checks are a v0.1 contract. Full revision-aware vendor adapters, survivorship reconstruction, and automated materiality analysis are later milestones.

Bias checks are not post-hoc warnings. They enforce whether the data was knowable when a decision was made. Every analytical path that combines time-varying datasets must preserve this property or explicitly record why it cannot.

## Ownership

The future `lacuna.bias` package owns:

- look-ahead and label-leakage detection;
- point-in-time join validation;
- revision and publication-lag checks;
- survivorship and universe-membership diagnostics;
- materiality estimates for detected bias;
- structured findings describing affected rows and periods.

Adapters expose source timestamps and source-specific metadata. They must not silently decide whether a record was historically available. Signal and validation modules consume bias-safe data; they must not repair unsafe joins internally.

## The temporal firewall

For a decision row `l` and a candidate information row `r`, the default admissibility rule is:

\[
r.available\_time \le l.decision\_time
\]

The join must also match stable entity keys, normally `instrument_id`, and any declared namespace such as venue or share class. If several admissible right-side rows exist, choose the greatest `available_time`; ties are resolved by an explicit revision or version field, never incidental row order.

An effective date is not proof of availability. A filing effective for quarter-end but published six weeks later is unavailable during those six weeks.

## Safe as-of join contract

A point-in-time join should accept:

- left and right table-like inputs;
- entity-key columns;
- the left decision-time column;
- the right availability-time column;
- an optional effective-time column;
- an optional revision/version column;
- a tolerance or maximum staleness;
- an exact-match policy;
- duplicate and unmatched-row policies.

It should return the joined table plus evidence containing:

- input and output row counts;
- unmatched and stale-match counts;
- the distribution of information age;
- duplicate-resolution counts;
- violations rejected before joining;
- resolved column mappings and time-zone assumptions.

The implementation must sort deliberately or prove that input ordering is valid. It must not mutate either input and must preserve the left row identity.

### Invariants

For every matched row:

1. entity keys agree;
2. `right.available_time <= left.decision_time`;
3. staleness is within the configured tolerance;
4. the chosen row is the most recently available admissible version;
5. output cardinality follows the declared duplicate policy;
6. the same inputs and configuration produce the same match.

## Revisions and restatements

Revision-aware datasets need at least:

- `effective_time`: when the fact applies economically;
- `available_time`: when this version became observable;
- `revision_time` or monotone `revision_id`: which historical version it is;
- `source_record_id`: stable source lineage when available.

Backtests use the version available at `decision_time`, not the latest restatement. If a source contains only the latest value, the result must carry an `UNKNOWN` revision-bias finding rather than claim point-in-time safety.

Corrections with an earlier effective date remain unavailable before their publication. Deletions and withdrawn records must be modeled as revisions if the source can represent them.

## Leakage classes

| Class | Example | Detection strategy |
| --- | --- | --- |
| direct look-ahead | tomorrow's close appears in today's feature | compare source availability with decision time |
| label overlap | a training label extends into the test interval | interval-overlap check and purging |
| cross-sectional leakage | same-day close used before the signal cutoff | validate field-specific availability policy |
| preprocessing leakage | scaler fitted on the entire sample | inspect fit-window provenance |
| selection leakage | features selected using held-out results | compare experiment and selection lineage |
| revision leakage | latest fundamentals used historically | require revision-aware source rows |
| universe leakage | only today's surviving securities are included | compare point-in-time membership evidence |
| regime leakage | regimes classified with future observations | validate regime computation window |

Checks should identify the earliest unsafe transformation when lineage is available. Downstream symptoms are useful evidence but do not replace the root cause.

## Survivorship and universe membership

A point-in-time universe record should contain `instrument_id`, `membership_start`, `membership_end`, `available_time`, and membership source. Membership intervals are half-open: `[membership_start, membership_end)`.

The audit distinguishes:

- **confirmed safe**: historical membership and delisted instruments are represented;
- **confirmed biased**: the data demonstrably filters by future survival;
- **unknown**: the source cannot establish historical membership.

Unknown is not equivalent to pass. However, it should not be converted into a failure without evidence.

## Materiality

When feasible, a finding should estimate impact by rerunning or comparing:

- safe versus unsafe joins;
- point-in-time versus latest-revision values;
- historical versus present-day universes;
- purged versus unpurged validation.

Report changes in sample size, coverage, IC, Sharpe-like metrics, and any decision-level classification. Materiality estimates must use the same downstream configuration and must declare when the comparison is only a proxy.

## Result contract

Bias analyses return an `AnalysisResult` with:

- summary metrics by leakage class;
- an affected-row sample with stable row identifiers;
- period and instrument concentration tables;
- one finding per independently actionable cause;
- provenance for timestamp mappings, join policy, and source limitations.

Sensitive source values should not be copied into findings. Stable identifiers and compact diagnostic samples are normally enough.

## Execution ownership

Sorted as-of matching, interval overlap, and large duplicate scans are strong Rust candidates after a correct Python reference exists. Source semantics, materiality orchestration, and finding construction remain in Python.

## Required tests

- equality at the decision-time boundary follows the exact-match policy;
- one-nanosecond future records are rejected;
- timezone-aware timestamps around daylight-saving changes remain ordered;
- revision ties resolve by the declared version, not row order;
- staleness limits reject old but otherwise admissible records;
- duplicate keys follow error, first, or aggregate policy exactly;
- interval endpoints honor half-open semantics;
- delisted instruments remain present in historical-universe fixtures;
- latest-only sources produce `UNKNOWN`, not `PASS`;
- shuffled/chunked inputs yield the same result;
- materiality comparisons keep downstream configuration fixed.

Synthetic fixtures should contain an obvious future record and an obvious delisted asset so a test cannot pass merely because no bias was present.
