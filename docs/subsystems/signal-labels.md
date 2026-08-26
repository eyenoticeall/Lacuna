# Signal analytics and forward labels

**Status:** v0.11 adds validated half-life inference and explicit one-horizon diagnostic portfolio
projections to the v0.10 transformation, attrition, grouping, and stability foundation. Weighted IC
and weighted bucketing remain later work.

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
          ├── explicit transformations
          │      bucketize / neutralize
          ├── IC / bucket returns / turnover / decay
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
Label evidence includes a `data_attrition` table. Each source-quality or horizon-eligibility row
records `input_rows`, `retained_rows`, `excluded_rows`, `excluded_fraction`, and the applied policy;
the counts reconcile exactly within that stage.

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

Tables include period IC, observation count, excluded count, and optional group/horizon keys.
Inference over the IC time series must account for serial dependence when claimed.

When `by` contains declared group columns, subgroup rows and pooled headline rows are computed
independently. Group columns survive alignment and appear in the period/horizon tables. A headline
metric never comes from the first subgroup. `group_available_time` proves that classifications were
available no later than observation time; future availability raises and absent availability emits
`GROUP_AVAILABILITY_UNKNOWN`.

## Weighted IC

Weights are non-negative finite values aligned row-wise. The result documents whether weights are normalized within period and which weighted covariance definition is used. Zero-total-weight groups are undefined, not zero.

## Explicit bucketing and quantile analysis

`BucketSpec` freezes assignment semantics before returns are examined:

```python
bucketed = lc.signal.bucketize(
    signal,
    spec=lc.BucketSpec.quantiles(
        10,
        tie_policy="preserve",
        split_at=0.0,
        equal_to="upper",
    ),
    by=("time", "sector"),
    available_time="sector_available_time",
)
bucket_evidence = lc.signal.bucket_returns(
    bucketed,
    labels,
    by=("observation_time", "sector"),
)
```

Supported specifications are quantiles, equal-width ranges, explicit numeric edges, and a binary
threshold. Numeric intervals are left-closed/right-open except for the final closed interval.
Quantile boundaries include zero and one and are strictly increasing. Balanced ties use stable
instrument identity as the final ordering key; preserve-ties uses average-rank percentiles and never
splits equal values. Split-aware quantiles allocate the odd extra bucket to the side selected by
`equal_to`.

Transformations raise on undersized groups and out-of-range edge values by default. Explicit drop
policies retain exact `data_attrition` rows and findings. Weighted buckets are intentionally absent
until their estimand and boundary-tie semantics are specified.

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

Turnover exposes distinct concepts:

- rank turnover between consecutive observations;
- top/bottom membership turnover;
- signal autocorrelation.

`lags=(1, ...)` uses positive global observation-index lags and always includes one. The legacy
`turnover_by_period` and lag-one headlines remain unchanged. Additive tables expose every requested
lag, common-instrument count, exact from/to observation times, rank turnover, autocorrelation, and
symmetric membership turnover for every bucket.

An instrument participates only when it exists at both exact endpoints. A missing intermediate row
does not prevent a lag-two comparison, and a missing endpoint is never replaced by the nearest row.
Portfolio-weight turnover is separate because a signal study does not contain portfolio weights.

## Decay

`decay()` evaluates IC and spread across the same explicit horizons and retains jointly aligned
period/horizon rows. `fit_decay()` fits the direction-adjusted positive model
`amplitude × exp(-horizon / tau)` and reports half-life `tau × log(2)` in trading observations.

A half-life estimate requires four positive horizons, twenty common periods, positive adjusted
means, convergence away from the upper bound, a finite stationary-block-bootstrap interval, and the
configured minimum `R²`. Failure returns `null` fields and a `WARN` or `UNKNOWN` finding. SciPy is
loaded only at the call site through `lacuna[statistics]`; optimizer, bounds, dependency version,
root entropy, substream derivation, and joint resampling policy are provenance.

## Diagnostic portfolio projection

`portfolio_projection()` accepts only an explicit bucket transformation and exactly one label
horizon. Callers select long/short buckets, equal/rank/absolute-signal weighting, gross/net
exposure, and optional joint group neutrality.

Leg magnitudes are `(gross + net) / 2` and `(gross - net) / 2`. Consequently, gross one and net zero
means `+0.5` long and `-0.5` short. Each output row stores observation, entry, label end, instrument,
horizon, bucket, leg, target weight, forward return, and arithmetic contribution. Evidence stores
exposure reconciliation, cohort return, coverage, concentration, implied one-way target turnover,
and attrition.

Group neutrality allocates each leg equally across eligible joint groups, then applies the selected
within-group weights. One-sided groups raise by default; explicit dropping renormalizes both legs
and records exclusions.

Per ADR-015, this is not a backtester. It does not compound returns, carry cash, resolve overlapping
cohorts, simulate orders/fills, infer execution, or apply costs. Its explicit weights can feed
Lacuna cost/capacity analysis or another backtester.

## Neutralization

`neutralize()` residualizes a signal against declared, already aligned exposures within each group.
It uses float64 `numpy.linalg.lstsq`, an intercept by default, deterministic reference-level
categorical encoding, and positive finite weights. A separate exposure frame joins on observation
time and stable instrument identity; the operation never performs an implicit as-of join.

The contract defines:

- intercept inclusion;
- categorical encoding and reference levels;
- weighting;
- collinearity/rank deficiency;
- missing exposures;
- minimum degrees of freedom;
- whether winsorization or standardization occurs before or after residualization.

The immutable result preserves `source_signal`, places residuals in canonical `signal`, and records
coefficients, matrix rank, condition, residual degrees of freedom, weighted fit diagnostics, and
attrition. Rank deficiency uses the minimum-norm solution with a finding. Insufficient residual
degrees of freedom raise by default. Exposure availability is verified when provided, future-dated
rows raise, and absent availability remains `UNKNOWN`.

Neutralization is a transformation result with diagnostics, not a hidden option inside IC. It does
not standardize, winsorize, join historical revisions, or choose exposures for the caller.

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
- Known single- and multi-lag turnover transitions, missing endpoints, and exact lag-one fixtures.
- Bucket edge closure, tie preservation, split-aware assignment, conservation, and permutation.
- Hand-solvable and weighted-orthogonality neutralization fixtures, rank deficiency, and invalid
  weights.
- Time-varying group classifications with verified, unknown, and future availability.
- Exact reconciliation for every `data_attrition` row.
- Known exponential recovery, sign reversal, flat/zero and upper-bound decay failures, and
  deterministic joint-period resampling.
- Exact portfolio gross/net/leg and contribution identities, the gross-one regression case,
  one-sided group policy, concentration, turnover, and permutation invariance.
- No same-close entry under `signal_time="close"`, `entry="next_open"`.
- Calendar, missing-bar, delisting, and last-horizon censoring.
- Eager/lazy and adapter equivalence.
- Native/reference differential tests.
- Null, NaN, infinity, duplicate, and timezone policies.

## Current boundary versus later

The current boundary includes forward returns, grouped Pearson/Spearman IC, explicit buckets,
quantile compatibility, spread, monotonicity, multi-lag turnover, neutralization, and descriptive
decay, validated half-life inference, and explicit diagnostic portfolio projections. Weighted IC,
weighted bucketing, abnormal-return event models, and cumulative portfolio simulation remain out of
scope. A native transformation kernel is not justified without profiling, a reference path, and
differential evidence.
