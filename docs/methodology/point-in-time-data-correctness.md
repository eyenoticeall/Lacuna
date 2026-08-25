# Point-in-time data correctness

Lacuna v0.4 treats historical knowability as a data contract, not a backtest option. The methods in
`lacuna.bias` answer bounded questions about the timestamps and universe records supplied by the
caller. They do not certify that a vendor's timestamps are true or that its archive is complete.

## Time roles

Keep these meanings separate:

| Time | Meaning |
| --- | --- |
| decision time | when the research process could act |
| effective time | when a fact applies economically |
| availability time | when this exact record became observable |
| revision/version | the ordering of published versions of one effective fact |
| membership interval | when an instrument belongs to a declared universe |

A quarter-end value is not usable at quarter end merely because it describes that quarter. If it
was published six weeks later, the publication timestamp controls admissibility.

## The temporal firewall

For a decision row (l) and information row (r), the default admissibility rule is:

\[
r_{available} \leq l_{decision}.
\]

`asof_join()` sorts both inputs deliberately, matches stable identity fields, and selects the
greatest admissible availability time. It preserves the original left-row order and cardinality
unless the caller chooses an explicit unmatched policy.

```python
joined = lc.bias.asof_join(
    decisions,
    fundamentals,
    left_time="decision_time",
    right_time="available_time",
    by="instrument",
    effective_time="fiscal_period_end",
    revision="revision_id",
    revision_mode="point_in_time",
    tolerance="180d",
)
```

The returned `PointInTimeJoinResult` contains the joined Polars frame and an `AnalysisResult` with
input/output counts, unmatched and stale counts, information-age summaries, tie evidence, resolved
semantics, adapter/materialization provenance, and a compact join sample.

### Exact matches and staleness

`allow_exact_matches=True` admits information timestamped exactly at the decision boundary. Set it
to `False` when the process requires the information to predate the boundary. `tolerance` rejects
otherwise admissible but stale records. A record rejected by tolerance is counted separately from
a genuinely absent historical record.

`unmatched` is explicit:

- `"keep"` preserves the decision row with null right-side fields;
- `"drop"` removes unmatched decisions and records the resulting cardinality;
- `"raise"` rejects the analysis if any decision lacks a match.

### Ties and revisions

Two records with the same identity and availability time are ambiguous unless an explicit revision
column resolves the tie. Incidental input order is never a version policy. With a revision field,
the greatest declared revision at the latest admissible availability time wins; duplicate
identity/availability/revision rows are rejected.

`revision_mode` records what the source can establish:

- `"point_in_time"` means historical versions are represented and requires a revision column;
- `"latest_only"` produces `UNKNOWN` revision-bias evidence;
- `"not_applicable"` declares that the field is not revised;
- `"unknown"` preserves uncertainty and is the default.

The output invariant is checked after the join: no selected availability time may be later than its
decision time. The method proves this relationship only for supplied timestamps.

## Direct future-data checks

`future_data_check()` inspects a dataset that already contains decision and availability fields:

```python
leakage = lc.bias.future_data_check(
    features,
    decision_time="decision_time",
    available_time="available_time",
    row_id="feature_row_id",
    instrument="instrument",
    materiality="absolute_weight",
)
```

Every row with `available_time > decision_time` fails. Equality is counted separately and remains
admissible. Missing availability stays `UNKNOWN`; it is never treated as zero lag or a passing row.
When `materiality` is supplied, Lacuna reports the absolute share attached to future rows without
assuming that the values are P&L. A bounded affected-row sample contains identifiers and timestamps,
not arbitrary sensitive feature values.

## Revision diagnostics

`revision_diagnostics()` groups versions by identity and effective time. It requires unique version
identities and tests whether availability is nondecreasing in explicit revision order.

```python
revisions = lc.bias.revision_diagnostics(
    fundamentals,
    entity=("instrument", "field"),
    effective_time="fiscal_period_end",
    available_time="available_time",
    revision="revision_id",
    value="value",
    source_mode="point_in_time",
)
```

The `facts` table reports version counts, first/last availability, and distinct value counts when a
value column is declared. Structural validity is a `PASS` only for a source declared
`point_in_time`. `latest_only` and `unknown` remain `UNKNOWN` even when the rows themselves are
well-formed. Lacuna cannot infer missing historical versions from a clean sequence.

## Survivorship evidence

Survivorship is a property of the source and its historical coverage, not merely of a filter
expression. `SurvivorshipStatus` has three states:

- `confirmed_safe`: historical intervals and delisted instruments are declared represented;
- `confirmed_biased`: the source demonstrably filters using future survival;
- `unknown`: completeness cannot be established.

Unknown is not pass. Confirmed safe is accepted only when the caller supplies a Boolean delisted
field and explicitly sets `includes_delisted=True`.

```python
survival = lc.bias.survivorship_diagnostics(
    membership,
    identity=("index", "instrument"),
    valid_from="valid_from",
    valid_to="valid_to",
    available_time="available_time",
    delisted="delisted",
    source_status="confirmed_safe",
    includes_delisted=True,
)
```

Diagnostics fail invalid or overlapping intervals and membership records that begin before they
become observable. Null availability produces independent `UNKNOWN` evidence. A structurally valid
safe declaration still carries a warning that vendor completeness was not independently verified.

## Membership intervals

Membership intervals are half-open:

\[
[valid\_from, valid\_to).
\]

An instrument is active at `valid_from` and inactive at `valid_to`. A null `valid_to` means the
interval remains open. Adjacent intervals may meet at an endpoint; overlapping intervals for the
same identity are rejected because selection would be ambiguous.

`membership_at()` applies two conditions:

1. the interval is active at `as_of`;
2. the membership record was available at `as_of`.

```python
members = lc.bias.membership_at(
    membership,
    as_of=rebalance_time,
    identity=("index", "instrument"),
    source_status="confirmed_safe",
)
```

Otherwise-active rows known only in the future are excluded and reported. The returned
`MembershipResult` includes the selected frame, source and candidate counts, excluded-row evidence,
and the source's survivorship status. Time filtering does not turn an unknown source into a safe
one.

## Universe drift

`universe_drift()` compares consecutive observed snapshot sets. For previous membership set (A)
and current set (B), it reports additions, removals, retained members, retention, Jaccard similarity,
and drift:

\[
J(A,B)=\frac{|A\cap B|}{|A\cup B|}, \qquad D(A,B)=1-J(A,B).
\]

```python
drift = lc.bias.universe_drift(
    snapshots,
    snapshot_time="snapshot_time",
    instrument="instrument",
    universe="index",
    source_status="unknown",
    warning_threshold=0.50,
)
```

Duplicate snapshot membership is rejected. A drift threshold is a review trigger, not a universal
economic cutoff. High drift can be legitimate; low measured drift does not prove that removed or
delisted securities were preserved.

## Declarative dataset validation

`DatasetSpec` makes structural assumptions reusable and inspectable:

```python
spec = lc.bias.DatasetSpec(
    name="fundamentals",
    required=("instrument", "effective_time", "available_time", "value"),
    keys=("instrument", "effective_time"),
    non_null=("instrument", "value"),
    numeric=("value",),
    temporal=("effective_time", "available_time"),
    temporal_order=(("effective_time", "available_time"),),
)
checked = lc.bias.validate_dataset(fundamentals, spec=spec)
```

Validation reports missing required fields, empty data, null constraints, duplicate logical keys,
invalid numeric/time dtypes, non-finite numbers, and temporal-order violations. Bad input returns a
structured failing result so audits can aggregate defects. An invalid `DatasetSpec` itself raises a
method-contract error because it is programmer configuration, not dataset evidence.

## Finding interpretation

Finding state and severity are independent. Typical outcomes are:

| Evidence | State |
| --- | --- |
| selected match is latest supplied nonfuture version | `PASS` |
| unmatched decision or excluded future-known membership | `WARN` |
| future data, invalid revision order, overlap, or confirmed bias | `FAIL` |
| latest-only revisions, missing availability, or unknown survivorship | `UNKNOWN` |

Do not suppress `UNKNOWN` findings to improve an audit score. Resolve them with stronger source
metadata or retain them as explicit limitations.

## Determinism, adapters, and execution

All public methods accept supported table-like inputs through the shared adapter boundary. As-of
selection is tested across eager/lazy Polars, pandas, and Arrow. Left decision order is stable;
membership selections are identity-sorted; revision and snapshot aggregations sort explicit keys.
Timezone-aware evidence is normalized to UTC for portable JSON serialization.

Polars owns sorting, joins, grouping, windows, and interval scans. NumPy is used only for compact
information-age summaries. The reproducible benchmark artifact includes
`bias.asof_join.reference`, covering validation, sorting, join execution, result construction,
checksum stability, throughput, and traced Python memory. No native bias kernel is claimed in v0.4.

## What v0.4 does not prove

- Vendor timestamps are accurate, complete, or recorded at the true market-usable instant.
- A `confirmed_safe` declaration has been independently audited.
- Field-specific cutoffs, exchange calendars, or after-close policies can be inferred from names.
- Corporate actions, identifier mapping, withdrawn records, and vendor-specific revision feeds are
  reconstructed automatically.
- Measured universe drift identifies the economic cause of composition changes.
- A safe join makes the downstream research design statistically valid.

These limits are why evidence includes source declarations, warnings, fingerprints, and semantic
column mappings instead of one universal “bias-free” flag.

## Verification coverage

The v0.4 path is covered by exact boundary, one-nanosecond future, timezone, revision-tie,
staleness, duplicate, delisted-asset, overlapping-interval, future-known membership, universe-drift,
and multi-defect dataset fixtures. Property tests enforce latest-nonfuture selection, right-input
permutation invariance, and half-open membership selection. Adapter, frozen API, benchmark, source
distribution, and clean-wheel smoke tests cover release boundaries.
