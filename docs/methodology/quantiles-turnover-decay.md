# Quantiles, turnover, and decay

These diagnostics describe signal shape and persistence without constructing a portfolio. All v0.1
methods return structured tables before any report is rendered.

## Balanced quantile assignment

`lacuna.signal.quantiles` sorts each group by signal and then instrument identity. With (n)
observations, requested count (Q), and one-based ordinal position (r):

```text
quantile = floor((r - 1) × Q / n) + 1
```

This conserves every eligible row and makes bin sizes differ by at most one. `ascending=True` places
the lowest signal in quantile 1. With `ascending=False`, signal order reverses while instrument identity
remains the deterministic final tie-breaker.

The v0.1 `balanced` tie policy may split equal signal values across a boundary. That choice keeps sizes
balanced and deterministic; it does not claim economically identical tied values belong together.
Groups with fewer than (Q) observations are excluded and counted. At least one group must remain.

## Quantile return evidence

For each group and quantile, Lacuna records the arithmetic mean return, median return, and observation
count. Across periods it reports the mean of period mean returns and median of period medians. These are
equal-period summaries, not a pooled observation-weighted mean.

For period (t):

```text
spread_t = mean_return(t, Q) - mean_return(t, 1)
```

`mean_top_bottom_spread` is the arithmetic mean of defined period spreads. No costs, leverage, or
portfolio normalization are applied.

Two monotonicity components are exposed:

- Spearman correlation between quantile number and across-period mean quantile return;
- fraction of adjacent mean-return differences that are strictly positive.

Flat adjacent returns do not count as ordered. A monotonicity value below 0.5 creates a weak-ordering
warning; the audit score uses separately versioned 0.4/0.7 thresholds.

## Rank turnover

`lacuna.signal.turnover` first maps average within-period ranks to `[0, 1]`:

```text
rank_fraction = (average_rank - 1) / max(n - 1, 1)
```

For instruments present in consecutive global observation periods:

```text
rank_turnover_t = mean_i(abs(rank_fraction(i,t) - rank_fraction(i,t-1)))
```

The table also contains Pearson correlation between raw current and previous signal values and the
number of common instruments. Instruments separated by a period gap are not treated as consecutive.

Top and bottom membership turnover uses the balanced quantile sets (A) and (B):

```text
membership_turnover = |A symmetric_difference B| / (|A| + |B|)
```

This symmetric measure ranges from 0 for identical sets to 1 for disjoint sets. It is not one-way
portfolio turnover and does not estimate traded notional.

## Horizon decay

`lacuna.signal.decay` applies Spearman IC and top-minus-bottom spread to a common multi-horizon label
set. `ic_decay` joins per-horizon IC summaries with mean/sample-standard-deviation spread summaries.

```python
decay = lc.signal.decay(
    signal,
    labels,
    min_observations=5,
    quantile_count=5,
)
```

The method intentionally does not fit a half-life. Three points do not by themselves identify an
exponential decay model, and non-monotonic curves can be informative. The result records
`half_life_policy="not_estimated_in_v0.1"` and carries a warning rather than manufacturing a number.

## Interpretation limits

- Quantile spreads are gross signal diagnostics, not strategy returns.
- High signal autocorrelation can coexist with membership churn near a quantile boundary.
- Low turnover does not establish low transaction costs without weights and execution assumptions.
- Decay across overlapping forward horizons is statistically dependent.
- Stable aggregate monotonicity can conceal unstable period-level spreads; inspect the source tables.

Property tests enforce row conservation/balance and deterministic ties. Unit fixtures cover static and
reversing ranks, known spreads, ordering, and multi-horizon joins.
