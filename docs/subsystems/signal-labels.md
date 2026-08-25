# Signal analytics and forward labels

**Status:** the v0.1 forward-label and signal-diagnostic APIs are implemented. Weighted IC,
neutralization, specialized half-life models, and additional tie policies remain later work.

This subsystem answers: does a cross-sectional feature contain predictive information under explicit earning and execution assumptions?

## Ownership

`lacuna.labels` owns label construction and label intervals. `lacuna.signal` owns comparisons between signals and already constructed labels.

The signal package must not infer trade execution timing from price column names. The labels package must not decide whether a signal is statistically credible.

## Canonical flow

```text
signal observations + prices
          │
          ├── validate observation timing
          ▼
explicit forward-return labels
          │
          ├── label_start / label_end
          ▼
aligned signal-label panel
          │
          ├── IC / quantiles / turnover / decay
          ▼
structured signal evidence
```

## Forward returns

Public functional API:

```python
labels = lc.labels.forward_returns(
    prices,
    horizons=["1D", "5D", "20D"],
    time="date",
    instrument="instrument",
    signal_time="close",
    entry="next_open",
    exit="close",
    price_adjustment="total_return_adjusted",
)
```

For entry price `P_entry` and exit price `P_exit`, the simple forward return is:

```text
r = P_exit / P_entry - 1
```

Log returns may be a later explicit method, never an implicit substitute.

### Timing contract

The label result contains:

- `observation_time` — signal timestamp;
- `label_start` — conservative sample-interval start at the signal observation;
- `entry_time` — actual entry observation used to select the entry price;
- `label_end` — actual exit timestamp;
- `horizon` — normalized requested horizon;
- `forward_return`.

A close-observed signal cannot use the same close as entry unless the caller explicitly defines a pre-close availability model. `next_open` resolves per instrument ordering and missing-bar policy. Starting the label interval at the signal observation is conservative for purging and keeps same-session entry/exit labels from collapsing to an empty interval when the source only has session timestamps.

### Horizon semantics

Duration strings must resolve to a documented clock:

- trading observations/sessions;
- calendar duration;
- explicit offset or timestamp mapping.

`5D` cannot silently mean calendar days in one adapter and five rows in another. The normalized method parameters record the resolved convention.

### Missing and corporate-action policy

Label construction defines:

- missing entry or exit price behavior;
- suspended/inactive instrument handling;
- delisting-return inclusion or an explicit unknown warning;
- price-adjustment status;
- duplicate bars;
- non-positive prices;
- timezone/calendar mismatch;
- last-period censoring.

Unknown price adjustment or delisting behavior becomes structured evidence in downstream audits.

## Alignment

Signal and labels align on stable instrument identity and observation time, never row position. Alignment must preserve label intervals and report:

- signal rows received;
- matched labels;
- rows dropped by policy;
- instruments and periods retained;
- duplicates or many-to-many joins prevented.

The v0.1 boundary rejects null semantic keys, non-numeric analytical values, incompatible signal and
label key dtypes, duplicate logical keys, incomplete interval metadata, non-positive intervals, and
entry times outside the supplied label interval. Optional external interval columns must use the same
physical time dtype as `observation_time`.

For lazy frames, projection and alignment should remain lazy until a grouped kernel requires materialization.

## Information coefficient

Public API:

```python
result = lc.signal.ic(
    signal,
    labels,
    method="spearman",
    by="observation_time",
)
```

### Pearson IC

Within each group, Pearson IC is the sample correlation between signal values `x` and forward returns `y`:

```text
IC = cov(x, y) / (std(x) × std(y))
```

The method documents `ddof`, weighting, minimum observations, and behavior for zero variance.

### Spearman IC

Spearman IC is Pearson correlation of within-group ranks. Tie behavior is explicit, initially average ranks. Nulls are removed according to paired policy before ranking.

The grouped rank kernel returns per-period values and counts. Aggregate statistics are computed from the IC time series, not by pooling every observation unless the user explicitly requests pooled IC and accepts its interpretation warning.

### IC result

Primary metrics:

```text
mean_ic
median_ic
std_ic
ic_information_ratio
t_statistic
positive_fraction
n_periods
n_observations
```

Tables include period IC, observation count, excluded count, and optional group/horizon keys. Inference over the IC time series must account for serial dependence when claimed.

## Weighted IC

Weights are non-negative finite values aligned row-wise. The result documents whether weights are normalized within period and which weighted covariance definition is used. Zero-total-weight groups are undefined, not zero.

## Quantile analysis

Public API:

```python
result = lc.signal.quantiles(
    signal,
    labels,
    quantiles=10,
    by="observation_time",
    tie_policy="balanced",
)
```

Quantiles are assigned within the declared group, usually each period. The assignment contract covers:

- ascending signal direction;
- ties at boundaries;
- group size smaller than quantile count;
- weighted quantiles;
- deterministic ordering;
- excluded values.

Outputs include count, mean/median return by quantile, top-minus-bottom spread, and confidence intervals when requested.

### Monotonicity components

Expose components rather than a vague score:

- Spearman correlation of quantile number with mean return;
- fraction of adjacent quantile pairs ordered in the expected direction;
- optional isotonic-fit error;
- counts and uncertainty.

No single component is labeled universal “signal quality.”

## Turnover

v0.1 exposes distinct concepts:

- rank turnover between consecutive observations;
- top/bottom membership turnover;
- signal autocorrelation.

Portfolio-weight turnover is later because a signal study does not contain portfolio weights.

Membership turnover must define entry, exit, and denominator conventions. Portfolio turnover distinguishes one-way from two-way turnover. Gaps in an instrument's observations are not automatically consecutive.

## Decay

Decay evaluates IC, spread, and relevant turnover across the same set of explicit horizons. The source table contains one row per horizon and group/summary statistic.

A half-life estimate is emitted only when the decay curve and model assumptions make it identifiable. Failed or non-monotonic fits carry a reason rather than an arbitrary number.

## Neutralization

Neutralization residualizes a signal against declared exposures within each period. Initial implementations should use mature weighted least-squares routines.

The contract defines:

- intercept inclusion;
- categorical encoding and reference levels;
- weighting;
- collinearity/rank deficiency;
- missing exposures;
- minimum degrees of freedom;
- whether winsorization or standardization occurs before or after residualization.

Neutralization is a transformation result with diagnostics, not a hidden option inside IC.

## Native candidates

Native execution:

- grouped average ranks and Spearman IC are implemented in Rust with a NumPy reference path;
- quantile assignment, grouped reductions, turnover, and signal autocorrelation currently use
  Polars/NumPy until benchmarks justify more native kernels.

Polars should own alignment, projection, and ordinary grouping unless benchmarks demonstrate otherwise.

## Required tests

- Hand-computed Pearson and Spearman groups.
- Rank invariance under strictly monotonic transforms.
- Average-rank tie fixtures.
- Constant signal/label and undersized groups.
- Quantile conservation and deterministic ties.
- Known turnover transitions.
- No same-close entry under `signal_time="close"`, `entry="next_open"`.
- Calendar, missing-bar, delisting, and last-horizon censoring.
- Eager/lazy and adapter equivalence.
- Native/reference differential tests.
- Null, NaN, infinity, duplicate, and timezone policies.

## v0.1 versus later

v0.1 includes forward returns, Pearson/Spearman IC, IC time series, quantiles, spread, monotonicity, turnover, and decay. Weighted/grouped extensions can land when their contracts are complete. Large repeated neutralization kernels and specialized estimators are later optimization work.
