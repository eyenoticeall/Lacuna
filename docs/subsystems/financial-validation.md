# Financial cross-validation and statistical inference

**Status:** v0.5 implements walk-forward, purged K-fold, CPCV with explicit path reconstruction,
IID/moving/circular/stationary and joint stationary bootstrap, permutation schemes, Sharpe/PSR/DSR,
CSCV/PBO, White Reality Check, and Hansen SPA.

This subsystem prevents ordinary validation machinery from ignoring time, overlapping labels, dependence, and repeated research trials.

## Ownership

`lacuna.cv` generates and explains temporal splits. `lacuna.validation` performs resampling, permutation, Sharpe inference, multiple-testing correction, and stability analysis.

Splitters return indices and a fold table. They do not fit models. Resampling functions accept statistics or supported statistic identifiers and return structured inference.

## Common interval model

Each sample used by a label-aware splitter has:

```text
observation_time
label_start
label_end
```

Intervals are initially modeled as half-open `[label_start, label_end)`. Two intervals overlap when:

```text
train_start < test_end and train_end > test_start
```

Boundary closure is part of the method version and appears in metadata.

## Fold representation

Every splitter produces a stable fold table:

```text
fold
role                 # train, purge, test, embargo
start
end
n_observations
[source_index ranges or mask reference]
```

This table is the source for visualization and audit evidence. Generated indices are inspectable; a splitter does not hide the actual path.

## Walk-forward validation

Public API:

```python
cv = lc.cv.WalkForward(
    train="5Y",
    test="1Y",
    step="6M",
    mode="expanding",
)
```

Modes:

- **expanding** — fixed train start, advancing train end;
- **rolling** — fixed-width train window;
- **anchored** — later explicit anchor with configured advance behavior;
- **fixed** — later caller-supplied calendar boundaries.

The splitter defines incomplete final-window behavior, timezone/calendar handling, minimum observations, and whether test windows overlap.

No random shuffle occurs.

## Purging

Purging removes a training observation when its label interval overlaps any test label interval for the fold. It is based on earning intervals, not an arbitrary number of adjacent rows.

Efficient implementations may merge test intervals and scan sorted train intervals. The result retains counts and, in debug output, the reason/range that caused removal.

Property invariant:

```text
for every retained train interval and every test interval:
    overlap == false
```

## Embargo

Embargo excludes observations in an additional region after the test boundary when the research design requires separation. It does not replace purging.

An embargo can be expressed as:

- a count of sorted unique observation periods in v0.1;
- clock/calendar duration in a later method;
- a fraction of available observations only in a later, explicitly named method.

The output separates purged and embargoed samples so users can understand why data was excluded.

## Purged walk-forward

A combined splitter is later work. v0.1 exposes `WalkForward` and `PurgedKFold` separately so it does
not falsely describe block K-fold as strictly past-only validation. A future combined method will
establish chronological train/test windows, purge overlapping training labels, then apply embargo in
that fixed order.

## CPCV and PBO

The two implemented methods are deliberately separate:

- `lacuna.cv.CombinatorialPurgedKFold` generates model-fitting splits, interval purging, embargo,
  and reconstructed test paths;
- `lacuna.validation.probability_of_backtest_overfitting` runs CSCV selection analysis over a
  synchronous matrix of already-computed strategy performance.

Together their evidence exposes:

- group partitioning;
- selected train/test combinations;
- purge/embargo effects;
- reconstructed backtest paths;
- relative out-of-sample ranks after explicit in-sample selection;
- logit distribution and PBO estimate;
- sensitivity to partition choice.

Do not call CPCV “PBO,” or call an ordinary combinatorial train/test splitter “CSCV.” Full method
definitions, equations, tie behavior, safety limits, and non-claims are in
[Advanced inference](../methodology/advanced-inference.md).

## Bootstrap framework

Public API:

```python
result = lc.validation.bootstrap(
    returns,
    statistic="mean",
    method="stationary",
    expected_block_length=20,
    resamples=50_000,
    seed=7,
)
```

Scalar bootstrap returns the observed statistic, resample distribution summary, interval, method
parameters, seed, raw/effective sample information, and warnings. Joint bootstrap instead reports
per-strategy means, standard errors, and the long-run covariance table. Built-in mean reducers use
private contiguous value/index/offset carriers; custom statistics remain on the Python path.

### IID bootstrap

Draw `n` observation indices independently with replacement. It is a reference and appropriate only when independence is defensible.

### Moving block bootstrap

Draw contiguous blocks of fixed length until at least `n` observations are produced, then truncate.
v0.1 starts blocks only where the complete block fits.

### Circular block bootstrap

As moving block bootstrap, but block indices wrap around the sample boundary.

### Stationary bootstrap

Draw geometric block lengths with restart probability `p`, choose each block start uniformly, wrap at
the sample boundary, and truncate to `n`. This is distributionally equivalent to continuing the
current block with probability `1 - p` or restarting uniformly with probability `p`, where expected
block length is `1 / p`.

The implementation validates positive expected length and records the exact parameterization.

## Confidence intervals

Implemented intervals are percentile and basic bootstrap intervals. BCa requires carefully
validated acceleration and jackknife behavior and should not be added as a label over an incomplete
implementation.

The result states interval level, sidedness, resample count, Monte Carlo resolution, and whether dependence-aware sampling was used.

## Permutation tests

Permutation schemes represent different null hypotheses:

- unrestricted permutation;
- within-period permutation;
- within-group permutation;
- block permutation;
- sign flip where symmetry justifies it.

The p-value calculation defines whether the observed arrangement is included and uses a finite-resample correction such as `(extreme + 1) / (resamples + 1)` when appropriate.

The alternative (`two_sided`, `greater`, `less`) is explicit. A within-date signal test must not
accidentally permute labels across dates.

## Sharpe inference

Sharpe calculations declare:

- `annualization` periods per year;
- that input is already an excess-return series;
- arithmetic mean and standard-deviation definitions;
- sample-standard-deviation `ddof=1`;
- missing values;
- empirical standardized central skewness and Pearson kurtosis;
- that the moment-based asymptotic equation does not separately correct autocorrelation.

Probabilistic Sharpe Ratio and Deflated Sharpe Ratio include all assumptions and trial inputs. DSR is not computed from a winning Sharpe without a documented estimate of selection multiplicity and expected maximum Sharpe.

## Later effective sample size

When defensible, expose both:

```text
n_raw
n_effective
```

The estimator and truncation/window rule are recorded. If no defensible estimator is available, effective size remains unknown rather than equaling raw size by default.

## Deterministic parallel randomness

Replicate `i` derives its random stream from `(root_seed, method_version, i)`. Results do not depend on worker scheduling or thread count.

Batch resamples to bound memory. The private execution budget accounts for the fixed result matrix,
sample-index bytes, and selected-value workspace before allocation. An explicit `memory_limit` is
never ignored. Batch size does not change replicate identities, RNG consumption, or results.

## Result contracts

Split result:

```text
fold_table
train/test index representation
purged_count
embargoed_count
coverage period
configuration and interval convention
```

Inference result:

```text
observed
estimate
standard_error
confidence_interval
p_value where applicable
n_raw / n_effective
resample summary/table
method metadata and warnings
```

## Native execution

- interval overlap/purge scan is implemented in Rust with a Python reference;
- deterministic bootstrap indices are generated in bounded Python batches and mean reductions are
  implemented in Rust with a NumPy reference;
- joint stationary bootstrap, Reality Check, and SPA generate the existing per-replicate PCG64
  substreams in Python and reduce equal-length index batches through a bounded NumPy
  indexed-column-mean reference;
- built-in Pearson permutation reuses invariant centered norms and performs one NumPy dot product
  per transformed sample; transformation streams and custom callables remain unchanged;
- CPCV and PBO currently use validated NumPy/Python reference paths. A multi-column
  Rust reducer is admitted only after the optimized reference remains material in the private v0.14
  full-call benchmark. No native RNG is used.

SciPy remains the default for mature distribution functions and standard linear algebra.

## Required tests

- Exact chronological fold fixtures.
- No retained interval overlap after purging.
- Boundary-touching half-open intervals do not overlap.
- Embargo count and duration behavior.
- IID bootstrap against independent reference indices.
- Fixed block and wraparound fixtures.
- Stationary block-length distribution simulation.
- Determinism across thread counts.
- Null false-positive and dependent-coverage simulations.
- Permutation preserves declared strata.
- Sharpe/PSR/DSR reference examples.
- Complete-family and selected-trial DSR validation.
- CSCV/PBO combination, selection, rank, logit, tie, and partition-sensitivity fixtures.
- Independent literal White and Hansen implementations, including direct long-run covariance sums.
- Reality Check/SPA null-size, power, and poor-alternative simulations.
- Undefined zero-variance and insufficient-sample cases.
- Native/reference differential tests and bounded-memory benchmarks.
