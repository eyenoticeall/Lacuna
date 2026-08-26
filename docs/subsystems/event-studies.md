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
observation-index interval `[-before, after + 1)`.

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

Stored outputs include mean response, pointwise percentile limits, simultaneous
max-standardized-deviation bands, event/cluster counts, and pre-event diagnostics. Root entropy,
stable substream identity, block configuration, and confidence are provenance.

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
