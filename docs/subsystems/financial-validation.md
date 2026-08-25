# Financial cross-validation and statistical inference

**Status:** v0.1 contract for walk-forward, simple purging, and basic block bootstrap. CPCV/PBO and advanced reality checks are later.

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

Target API:

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
- **anchored** — explicit anchor with configured advance behavior;
- **fixed** — caller-supplied calendar boundaries.

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

- clock/calendar duration;
- trading sessions;
- fraction of available observations, only when explicitly requested.

The output separates purged and embargoed samples so users can understand why data was excluded.

## Purged walk-forward

A combined splitter first establishes chronological train/test windows, then purges overlapping training labels, then applies embargo. The ordering is fixed and documented.

## CPCV and PBO

Combinatorial purged cross-validation is later. Its implementation must expose:

- group partitioning;
- selected train/test combinations;
- purge/embargo effects;
- reconstructed backtest paths;
- relative out-of-sample ranks;
- logit distribution and PBO estimate;
- sensitivity to partition choice.

Do not introduce a simplified “PBO” that omits path construction or selection logic.

## Bootstrap framework

Target API:

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

All methods return the observed statistic, resample distribution summary, interval, method parameters, seed, raw/effective sample information, and warnings.

### IID bootstrap

Draw `n` observation indices independently with replacement. It is a reference and appropriate only when independence is defensible.

### Moving block bootstrap

Draw contiguous blocks of fixed length until at least `n` observations are produced, then truncate. The contract states whether blocks can start only where a full block fits.

### Circular block bootstrap

As moving block bootstrap, but block indices wrap around the sample boundary.

### Stationary bootstrap

At each step, continue the current block with probability `1 - p` or start at a uniformly drawn index with probability `p`, where expected block length is `1 / p`.

The implementation validates positive expected length and records the exact parameterization.

## Confidence intervals

Initial intervals may include percentile and basic bootstrap intervals. BCa requires carefully validated acceleration and jackknife behavior and should not be added as a label over an incomplete implementation.

The result states interval level, sidedness, resample count, Monte Carlo resolution, and whether dependence-aware sampling was used.

## Permutation tests

Permutation schemes represent different null hypotheses:

- unrestricted permutation;
- within-period permutation;
- within-group permutation;
- block permutation;
- sign flip where symmetry justifies it.

The p-value calculation defines whether the observed arrangement is included and uses a finite-resample correction such as `(extreme + 1) / (resamples + 1)` when appropriate.

The alternative (`two-sided`, `greater`, `less`) is explicit. A within-date signal test must not accidentally permute labels across dates.

## Sharpe inference

Sharpe calculations declare:

- return frequency and `periods_per_year`;
- risk-free/excess-return treatment;
- arithmetic mean and standard-deviation definitions;
- `ddof`;
- missing values;
- skewness/kurtosis estimator;
- autocorrelation treatment.

Probabilistic Sharpe Ratio and Deflated Sharpe Ratio include all assumptions and trial inputs. DSR is not computed from a winning Sharpe without a documented estimate of selection multiplicity and expected maximum Sharpe.

## Effective sample size

When defensible, expose both:

```text
n_raw
n_effective
```

The estimator and truncation/window rule are recorded. If no defensible estimator is available, effective size remains unknown rather than equaling raw size by default.

## Deterministic parallel randomness

Replicate `i` derives its random stream from `(root_seed, method_version, i)`. Results do not depend on worker scheduling or thread count.

Batch resamples to bound memory. Do not allocate the full index matrix when the statistic can be reduced in streaming batches.

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

## Native candidates

- interval overlap/purge scan;
- combinatorial index generation;
- moving/circular/stationary bootstrap indices and reductions;
- large permutation reductions;
- later PBO components.

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
- Undefined zero-variance and insufficient-sample cases.
- Native/reference differential tests and bounded-memory benchmarks.
