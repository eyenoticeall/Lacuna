# Bias detection and point-in-time safety

**Status:** implemented for the v0.4 data-correctness milestone. Vendor-specific adapters,
automated downstream materiality reruns, identifier-history reconstruction, and external source
certification remain later work.

The shipped `lacuna.bias` surface includes safe as-of joins, direct future-data checks, revision
diagnostics, survivorship declarations, half-open membership selection, universe drift, and
declarative dataset validation. Exact public behavior and examples are documented in
[Point-in-time data correctness](../methodology/point-in-time-data-correctness.md).

Bias checks are not post-hoc warnings. They enforce whether the data was knowable when a decision was made. Every analytical path that combines time-varying datasets must preserve this property or explicitly record why it cannot.

## Ownership

The `lacuna.bias` module owns:

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

### Implemented parameter semantics

- **`effective_time`** is validated as a time column on the right input and recorded in
  provenance. It does **not** affect matching: admissibility and recency use `available_time`
  alone, with `revision` resolving availability ties, and the result carries a warning saying so.
  Consequently a late restatement of an older period outranks a newer period's first print.
  Whether matching should additionally order by effective time is an open design question; no
  such semantics are defined or implied.
- **`tolerance`** must match the unit system of the decision-time column. Integer (or
  whole-number float) time takes a non-negative whole number of index units. Date, Datetime,
  and Duration time take a `timedelta` or a fixed-length duration string built from `ns`, `us`,
  `ms`, `s`, `m`, `h`, `d`, `w` (for example `"30d"`, `"1h30m"`). A bare number on temporal time,
  a duration string on index time, negative strings, uppercase units, and calendar-variable units
  (`mo`, `q`, `y`) are rejected with `MethodContractError` before any join runs.
- **`revision`** must have an intended sort order: integer, finite float, Date, Datetime,
  Duration, or Enum (declared category order). String and categorical revisions are rejected
  with `DataContractError` because they sort lexicographically (`"10"` ranks below `"9"`); cast
  to an integer or declare an Enum. The dtype is checked whenever `revision` is declared, not only
  when ties exist. `revision_diagnostics` (method version 2) applies the same rule; through 0.14.2
  it accepted string and categorical revisions and could report a false
  `BIAS_REVISION_ORDER_INVALID` from their lexicographic order.
- **Duration** time and revision columns are supported. Evidence tables and fingerprints record a
  duration as ISO 8601 text (`P1D`, `PT1H30M`), which does not depend on the column's time unit.
  Through 0.14.2 every `Duration` column failed with a Polars cast error.
- **Method version:** `bias.asof_join` is version 2. The validated tolerance, the rejected revision
  dtypes, and the computed `future_matches` shipped in 0.14.2 while the result still reported
  version 1, so version-1 results from 0.14.2 and from earlier releases are not comparable.
- **`future_matches`** is computed from the joined output (matched rows whose availability is
  later than the decision time) rather than asserted. A nonzero count raises rather than returning
  a frame containing future data.

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

A `confirmed_safe` declaration is corroborated only when the delisted column marks at least one
row. If it marks none (all `False` or null), `survivorship_diagnostics` emits
`BIAS_SURVIVORSHIP_DELISTINGS_NOT_OBSERVED` (`UNKNOWN`) instead of `BIAS_SURVIVORSHIP_SAFE`.

`universe_drift` compares consecutive snapshots, so drift is undefined for a universe with fewer
than two snapshots. Any such universe (including one hidden behind another universe's
transitions) yields `BIAS_UNIVERSE_DRIFT_UNDEFINED` (`UNKNOWN`), never
`BIAS_UNIVERSE_DRIFT_MEASURED`, and `mean_drift` / `maximum_drift` are `null` when there are no
transitions. Both methods are at `method_version` 2.

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

Polars owns sorted as-of matching, interval overlap, grouping, and duplicate scans in v0.4. These
operations are benchmarked as complete public workflows. A Rust implementation requires measured
need, an independent reference path, and differential tests. Source semantics, materiality
orchestration, and finding construction remain in Python.

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
