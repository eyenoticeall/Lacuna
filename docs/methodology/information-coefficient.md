# Information coefficient

`lacuna.signal.ic` estimates cross-sectional association between a signal and already constructed
forward returns. Method version `1` provides Pearson and average-rank Spearman information
coefficients (ICs).

## Alignment and eligibility

Tabular inputs align by `(observation_time, instrument)`; row position is never identity. When labels
contain `horizon`, one signal row may align to multiple horizon rows and horizon is automatically part
of the group key. Duplicate logical keys are errors.

Null and NaN signal/return pairs are jointly dropped under `null_policy="drop"` or rejected under
`"raise"`. Infinity is always rejected. Groups smaller than `min_observations` (default 3) are excluded
and counted. If no eligible group remains, computation fails rather than returning a fabricated zero.

## Pearson IC

Within group (g), with paired values (x_j) and (y_j):

```text
IC_g = Σ((x_j - mean(x)) (y_j - mean(y)))
       / sqrt(Σ(x_j - mean(x))² × Σ(y_j - mean(y))²)
```

The value is clipped to `[-1, 1]` against floating-point overshoot. Fewer than two observations or zero
variance makes the group undefined.

## Spearman IC and ties

Spearman IC applies the Pearson formula to within-group ranks. Equal values receive the average of
their occupied one-based ranks. This is distinct from the balanced ordinal rule used for quantile
assignment. The NumPy reference and Rust grouped-rank kernel implement the same tie contract.

Any strictly increasing transformation of a signal preserves Spearman IC when its tie relationships
are unchanged. It does not generally preserve Pearson IC.

## Time-series aggregation

Defined group ICs form the authoritative `ic_by_period` table. Across its (T) defined values:

```text
mean_ic             = mean(IC_t)
median_ic           = median(IC_t)
std_ic              = sample standard deviation, ddof=1
ic_information_ratio = mean_ic / std_ic
t_statistic         = mean_ic / (std_ic / sqrt(T))
positive_fraction   = count(IC_t > 0) / T
```

The information ratio is not annualized. The reported t-statistic is the ordinary independent-period
formula and always carries a warning that serial dependence is not adjusted. Use a dependence-aware
bootstrap over the IC series for uncertainty; do not quote this t-statistic as robust inference when
labels or signal states overlap.

If no IC is defined, nullable aggregate metrics remain `null`. One defined period has a mean/median but
no sample standard deviation, ratio, or t-statistic. Fewer than 20 defined groups produces
`IC_PERIOD_SUPPORT_LOW`.

## Multiple horizons

With long-form labels, IC is evaluated separately by observation period and horizon. The
`ic_by_horizon` table reports mean, median, sample standard deviation, information ratio, defined-period
count, and observation count per horizon. It is an aggregation of the period ICs, not a pooled
cross-section.

## Example

```python
result = lc.signal.ic(
    signal,
    labels,
    method="spearman",
    by="observation_time",
    min_observations=5,
)

print(result.metrics["mean_ic"])
period_ic = result.table("ic_by_period")
```

IC measures association, not tradable portfolio return. It ignores sizing, constraints, transaction
costs, borrow, and capacity. A positive IC can coexist with an untradeable or unstable strategy.

## Validation evidence

Tests include hand-computed Pearson and tied Spearman examples, SciPy reference comparisons, strict
monotonic-transform invariance, shuffled-row alignment, constant/undersized groups, randomized
native/reference differentials, and adapter/lazy equivalence.
