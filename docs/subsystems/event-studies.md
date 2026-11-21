# Event studies

**Target:** v0.11. This contract defines availability-anchored event windows and dependence-aware
path inference. It does not infer an abnormal-return risk model.

## Research question and ownership

`lacuna.events` asks how observed price-relative paths behave around events that were actually
available to a decision process. It owns event/price alignment, path coverage, overlap evidence, and
clustered inference. It does not own event discovery, fundamental revision joins, trading orders,
or a market-model benchmark.

## Canonical inputs

Events require stable `event_id`, `instrument`, `event_time`, and `available_time`. Prices require
stable instrument identity, observation time, a positive finite price field, and an explicit
adjustment policy. Keys cannot be null or duplicated.

Availability time is the default anchor. `anchor="event_time"` is an explicit retrospective view;
when `available_time > event_time`, the result records lookahead delay evidence. The alignment rule
selects the first eligible observation at or after the anchor for the same instrument. It never
uses row position across instruments or the nearest earlier price.

## Window contract

Offsets are integers from `-before` through `+after`, inclusive. The event path is the price at each
offset divided by the anchor price minus one. Provenance records the equivalent half-open
observation-index interval `[-before, after + 1)`. The offset-0 row is the anchor price itself, so
its response is the exact identity `p/p - 1 = 0`; it is emitted as a literal `0.0`, never as a
rounded or residual value. Other offsets are computed as `price / anchor_price - 1` and stored at
full precision.

Each result row contains event identity, instrument, event/availability/anchor/aligned times,
offset, price time, price, anchor price, and raw response. Missing leading or trailing observations
are censoring, not zero response. Coverage tables expose expected/observed rows, anchor delay,
censoring side, and adjustment policy.

Duplicate event identities raise. Same-instrument windows that share a price observation raise by
default. Explicit retention assigns deterministic overlap-cluster identities and records affected
events; it does not assert their independence.

## Response inference

`event_response()` resamples complete event paths, never individual offsets. Events are ordered by
aligned anchor time and grouped into anchor-time clusters so cross-sectional events sharing a date
remain together. A stationary block bootstrap resamples those ordered clusters jointly across all
offsets.

The resampling unit is the aligned anchor time only. The `overlap_cluster` column on the windows
table (same-instrument windows that share a price observation) is carried as evidence but is **not**
a resampling unit; the stationary block bootstrap over ordered anchor-time clusters is the only
dependence adjustment applied. `EVENT_CLUSTERED_INFERENCE_AVAILABLE` therefore states
`clustering_unit="aligned_anchor_time"`, `overlap_cluster_used_for_resampling=false`, and the number
of overlap clusters with more than one event and the events they contain (`null` when a hand-built
windows frame has no `overlap_cluster` column).

The response result propagates every `WARN`, `FAIL`, and `UNKNOWN` finding of the supplied windows
result unchanged (overlap, censoring, retrospective lookahead, unknown price adjustment), after its
own finding and in the windows result's stored order, without duplicates. An audit that sees only
the response therefore cannot miss them. This applies to both the inferential and the
insufficient-support results.

Stored outputs include mean response, pointwise percentile limits, simultaneous
max-standardized-deviation bands, event/cluster counts, and pre-event diagnostics. Root entropy,
stable substream identity, block configuration, and confidence are provenance. A caller-supplied
`seed` is also recorded as `metadata.seed` (null when no seed was given; the generated root entropy
is then only in `parameters["root_entropy"]`). `events.event_response` is method version 2:
version 2 adds the propagated findings, the explicit clustering-unit evidence, and `metadata.seed`.

Fewer than the declared minimum clusters returns descriptive means with inferential fields `null`
and an `UNKNOWN` finding. Zero-variance offsets likewise have no standardized simultaneous bound.
No independent-event standard error is substituted.

## Deliberate exclusions

- no market, sector, or multifactor expected-return model;
- no event-time anchor by default;
- no silent overlap removal;
- no cumulative strategy P&L or order simulation;
- no forward filling across missing prices;
- no calendar inference from timestamp frequency.

## Required evidence and tests

- exact anchor equality and next-observation boundaries;
- explicit event-versus-availability delay and retrospective lookahead findings;
- left/right censoring and missing-price attrition;
- duplicate and overlap policies;
- permutation-stable event identity and overlap clusters;
- complete-path clustered resampling with deterministic root entropy;
- pointwise and simultaneous interval identities on hand-solvable paths;
- zero variance, fewer-than-minimum clusters, and planted pre-event response;
- fixed-seed calibration simulations over clustered events.
