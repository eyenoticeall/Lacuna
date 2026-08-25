# Bootstrap inference

`lacuna.validation.bootstrap` estimates uncertainty for an ordered one-dimensional statistic. Method
version `1` implements IID, moving-block, circular-block, and stationary resampling with deterministic
per-replicate streams.

## Input and statistic

Inputs may be a one-dimensional NumPy array, Python sequence, or supported table with a named `value`
column. At least two finite observations must remain. Null/NaN values are dropped or rejected by
`null_policy`; infinity is always an error.

Supported statistic identifiers are:

| Statistic | Definition |
| --- | --- |
| `mean` | arithmetic mean |
| `median` | sample median |
| `sharpe` | arithmetic mean divided by sample standard deviation (`ddof=1`), unannualized |

A callable receives a float64 NumPy array and must return a finite scalar. Callable code executes in
Python and does not use the native mean reducer.

## Resampling schemes

Let (n) be sample size and (L) the resolved block length.

- **IID:** draw (n) indices independently and uniformly from `[0, n)`.
- **Moving:** draw starts uniformly from `[0, n-L]`, append complete non-wrapping blocks of length
  (L), and truncate to (n).
- **Circular:** draw starts uniformly from `[0, n)`, append length-(L) blocks modulo (n), and
  truncate.
- **Stationary:** draw geometric block lengths with restart probability (p=1/L); draw each block
  start uniformly, wrap modulo (n), and stop after (n) values. This is distributionally equivalent
  to continuing an index with probability (1-p) and restarting uniformly with probability (p).

IID rejects a block length. Stationary accepts `expected_block_length`; the other block methods use
`block_length`. When a dependence-aware method omits (L), v0.1 uses
`max(2, round(n ** (1/3)))`. The value must not exceed the sample size. This default is a reproducible
starting point, not an optimal-block estimator.

## Deterministic random streams

Replicate (i) uses NumPy PCG64 initialized from:

```text
SeedSequence([root_seed, method_version=1, replicate_index])
```

Changing batch size or scheduling therefore does not change a replicate. An explicit seed overrides
the scoped Lacuna seed. If neither exists, Lacuna draws 63 bits of system entropy and records the
resolved seed; the run can then be reproduced from its metadata.

Indices are generated in bounded batches. The approximate batch count is limited by
`batch_memory_bytes / (n × sizeof(intp))`, with a minimum memory budget of 1,024 bytes. Mean
replicates can be reduced by the Rust kernel; index generation stays in Python so native and reference
paths use identical streams.

## Intervals and output

At confidence level `1 - alpha`, percentile bounds are empirical quantiles `q(alpha / 2)` and
`q(1 - alpha / 2)`. Basic bounds reflect those quantiles around the observed statistic:

```text
lower_basic = 2 × observed - q_upper
upper_basic = 2 × observed - q_lower
```

NumPy's default quantile interpolation is used. Bootstrap standard error is the sample standard
deviation (`ddof=1`) of replicates. At least 100 resamples are required, and
`monte_carlo_resolution = 1 / (resamples + 1)` is reported. `distribution_summary` stores fixed
quantiles; `store_distribution=True` additionally stores every replicate.

## Assumptions and warnings

IID output carries a structured independence warning. Block methods warn that sensitivity to (L)
must be checked. v0.1 leaves `n_effective` unknown rather than equating it to raw sample size.

Bootstrap intervals describe the chosen estimator under the empirical dependence scheme. They do not
correct selection bias, nonstationarity, universe bias, or a poorly chosen block length. In
`SignalStudy.audit`, stationary bootstrap is applied to the defined IC series with at least two values;
the report does not pretend this validates all research choices.

Validation includes deterministic index fixtures, batch-size invariance, native/reference
differentials, restart-frequency simulation, and a fixed-seed AR(1) coverage guard.
