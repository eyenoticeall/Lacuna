# Advanced inference and backtest-overfitting controls

Lacuna v0.5 adds selection-aware inference without treating unlike procedures as synonyms.
`CombinatorialPurgedKFold` is a model-fitting splitter. CSCV/PBO consumes a synchronous matrix of
already-computed strategy performance. White's Reality Check and Hansen's SPA test a declared
family against one benchmark. PSR/DSR describe uncertainty around a Sharpe estimate and its
selection process. Each method answers a narrower question than “is this strategy valid?”

The public entry points live under `lacuna.cv` and `lacuna.validation`. All return inspectable
indices or `AnalysisResult` evidence; none fits a model, chooses a block length, estimates an
effective trial count, or discovers the complete research family on the caller's behalf.

## Combinatorial purged cross-validation

```python
split = lc.cv.CombinatorialPurgedKFold(
    n_groups=6,
    n_test_groups=2,
    embargo=2,
).split(
    labels,
    time="observation_time",
    label_start="label_start",
    label_end="label_end",
)
```

Let `N` be the number of contiguous chronological groups and `k` the number held out per split.
Lacuna constructs all `C(N, k)` test-group combinations in lexicographic order. For each
combination it:

1. selects every row whose observation time belongs to a held-out group;
2. treats all remaining rows as training candidates;
3. purges a candidate if its half-open label interval overlaps any test label interval;
4. embargoes retained candidates in the configured number of periods after every held-out group;
5. records train, test, purge, and embargo source-row indices separately.

Every group appears in `C(N - 1, k - 1)` test combinations. Those ordered incidences define the
same number of reconstructed paths. A `CPCVPath` exposes one contributing fold for every group and
the complete chronological test-index sequence. The `groups`, `combinations`, `folds`, and `paths`
tables make partitioning and reconstruction auditable.

The safety limit `max_combinations` is checked before any split work. Raising it is an explicit
decision to accept combinatorial cost. Uneven group widths are allowed when the number of distinct
periods is not divisible by `N`; all rows for one period stay together. CPCV may train on data after
a test group and therefore does not mean “strictly past-only.” Purging prevents label-interval
overlap; it does not turn block cross-validation into walk-forward validation.

## Permutation tests

```python
test = lc.validation.permutation_test(
    observations,
    value="signal",
    paired_with="forward_return",
    statistic="pearson",
    scheme="within_date",
    permutations=10_000,
    alternative="two_sided",
    seed=7,
)
```

The transformation declares the null:

| Scheme | Transformation | Required contract |
| --- | --- | --- |
| `sign_flip` | independently multiply each value by `-1` or `+1` | distribution is symmetric under the zero-centered null |
| `unrestricted` | permute values across all observations | values are exchangeable relative to `paired_with` |
| `within_date` | permute only within each time value | exchangeability holds within dates, never across them |
| `within_group` | permute only within each declared group | exchangeability holds within groups |
| `block` | reorder non-overlapping chronological blocks | blocks are exchangeable; order within each block is preserved |

Non-sign-flip schemes require `paired_with` and reject the built-in, permutation-invariant `mean`.
Built-in `mean` therefore belongs to sign-flip inference; built-in `pearson` belongs to paired
permutation. A callable receives `(permuted_values, fixed_paired_values_or_none)` and must return a
finite scalar.

For `greater`, Lacuna counts permuted statistics at least as large as observed. `less` reverses the
comparison. `two_sided` compares absolute magnitudes. All use the finite-resample correction:

```text
p = (1 + number of equally or more extreme replicates) / (B + 1)
```

Replicate `i` uses `SeedSequence([seed, 2, i])`. The output records the exact scheme, stratum,
alternative, statistic, resolved seed, Monte Carlo resolution, and optional full distribution.
The method does not diagnose whether exchangeability is true; its warning keeps that obligation
visible.

## Sharpe uncertainty, PSR, DSR, and minimum track record

```python
inference = lc.validation.sharpe_inference(
    excess_returns,
    benchmark=0.5,
    annualization=252,
    confidence_level=0.95,
    trial_sharpes=all_eligible_annualized_sharpes,
    independent_trials=effective_trial_count,
)
```

Returns are treated as excess returns supplied at one sampling frequency. Lacuna uses the
arithmetic mean, sample standard deviation (`ddof=1`), empirical standardized central skewness,
and Pearson kurtosis (`normal = 3`). `annualization` scales Sharpe values by its square root; the
inference equations operate at the unannualized observation frequency.

For observed periodic Sharpe `SR`, sample length `T`, skewness `g3`, and kurtosis `g4`, define:

```text
A = 1 - g3 * SR + ((g4 - 1) / 4) * SR^2
SE(SR) = sqrt(A / (T - 1))
PSR(SR0) = Phi((SR - SR0) / SE(SR))
```

`A` must be positive and finite. The reported interval is a two-sided asymptotic normal interval at
the declared confidence level. The PSR threshold and minimum track-record calculation are
one-sided. When `SR > SR0`, minimum track-record length in observations is:

```text
MinTRL = 1 + A * (Phi^-1(confidence_level) / (SR - SR0))^2
```

When the observed Sharpe does not exceed the benchmark, `minimum_track_record_observations` is
unknown rather than infinity because result JSON forbids non-finite values.

DSR is computed only when the complete eligible `trial_sharpes` family is supplied and contains
the selected strategy's observed Sharpe. Let `N` be the declared effective independent-trial count,
`mu_SR` and `sigma_SR` the mean and sample standard deviation across supplied trial Sharpes, and
`gamma` the Euler–Mascheroni constant. The multiplicity-adjusted expected maximum is:

```text
SR* = mu_SR + sigma_SR * (
    (1 - gamma) * Phi^-1(1 - 1/N)
    + gamma * Phi^-1(1 - 1/(N*e))
)
DSR = PSR(SR*)
```

For one effective trial or zero between-trial variance, the threshold is `mu_SR`. The effective
count must lie between one and the visible trial count. If omitted, Lacuna uses the supplied count,
records the independence assumption, and warns. It never infers the hidden number of experiments
from the winning result. The `trial_sharpes` table preserves the full declared family.

PSR/DSR are asymptotic moment-based procedures. Short samples, unstable fourth moments,
autocorrelation, changing strategy behavior, unrecorded trials, and post-selection edits can make
the result misleading even when the calculation is exact.

## CSCV and probability of backtest overfitting

```python
pbo = lc.validation.probability_of_backtest_overfitting(
    synchronous_strategy_returns,
    partitions=8,
    statistic="sharpe",
    partition_sensitivity=(4, 6, 10),
)
```

The input is a true `T x M` matrix: rows are synchronous observations and columns are every
eligible strategy configuration. This is CSCV, not CPCV. It does not train models or use label
intervals. `T` must divide every requested even partition count `S`, producing equal contiguous
submatrices as required by the reference algorithm.

For all `C(S, S/2)` in-sample group combinations, Lacuna:

1. uses the complementary groups out of sample;
2. computes mean or unannualized Sharpe for every strategy on each half;
3. selects the best in-sample strategy;
4. ranks that selected strategy among all out-of-sample strategies, lowest to highest, using
   average ranks for OOS ties;
5. computes relative rank `omega = rank / (M + 1)` and `logit = log(omega / (1 - omega))`;
6. marks the selection as overfit when `logit <= 0`, meaning it is at or below the OOS median.

PBO is the fraction of combinations marked overfit. Every selection, IS/OOS group set, strategy,
performance, rank, relative rank, and logit appears in the `combinations` table. The
`partition_sensitivity` table repeats PBO for every requested `S`.

An in-sample top tie is an ambiguous selection decision. The default `tie_break="raise"` refuses
it. `tie_break="first"` is available only when declared column order is a defensible deterministic
selection rule, and the result counts and warns about every such tie. `max_combinations` bounds
work before enumeration.

PBO describes the supplied family and partition design. It is not a frequentist p-value, does not
recover unreported trials, and does not prove a strategy is deployable. A low estimate on a curated
or survivorship-biased strategy matrix is weak evidence.

## Joint stationary bootstrap

```python
joint = lc.validation.joint_stationary_bootstrap(
    performance_differentials,
    expected_block_length=20,
    resamples=10_000,
    seed=7,
)
```

Each replicate uses one stationary-bootstrap index path for the entire matrix. With restart
probability `q = 1 / expected_block_length`, an index continues modulo `T` with probability
`1 - q` and restarts uniformly with probability `q`. Sharing indices preserves contemporaneous
cross-strategy dependence while random-length blocks preserve local serial dependence.

The result reports each observed and bootstrap mean plus the covariance of
`sqrt(T) * (bootstrap_mean - observed_mean)`. Replicate `i` uses
`SeedSequence([seed, 3, i])`. Full replicate-by-strategy means are stored only when requested.

This is the resampling primitive used conceptually by Reality Check and SPA. It does not choose an
optimal expected block length. Sensitivity across plausible values is part of the research design.

## White's Reality Check

```python
check = lc.validation.reality_check(
    performance_differentials,
    expected_block_length=20,
    resamples=10_000,
    seed=7,
)
```

Each cell is a candidate's performance differential versus one common benchmark. Positive means
the candidate is better. For strategy means `dbar_k`:

```text
T_RC = max(0, max_k(sqrt(T) * dbar_k))
```

The full differential matrix is jointly stationary-bootstrapped. White's least-favorable null is
imposed by centering every bootstrap mean at its sample mean:

```text
T_RC*(b) = max(0, max_k(sqrt(T) * (dbar_k*(b) - dbar_k)))
```

The p-value uses the same finite correction as permutation tests. Replicate `i` uses
`SeedSequence([seed, 4, i])`. If every candidate sample mean is non-positive, the observed
statistic is zero and the p-value is one.

Reality Check controls data snooping over the declared family, but its least-favorable null can
become very conservative when many poor or erratic alternatives are included. That behavior is a
property of the method, not a reason to delete candidates after seeing results.

## Hansen's Superior Predictive Ability test

```python
spa = lc.validation.superior_predictive_ability(
    performance_differentials,
    expected_block_length=20,
    resamples=10_000,
    seed=7,
)
```

SPA uses the same positive-is-better differential contract but studentizes each candidate. With
stationary restart probability `q`, centered series autocovariance `gamma_hat(i)`, and sample size
`T`, Hansen's stationary-bootstrap population variance is:

```text
kappa(T, i) = ((T-i)/T) * (1-q)^i + (i/T) * (1-q)^(T-i)
omega_hat_k^2 = gamma_hat_k(0) + 2 * sum(i=1..T-1, kappa(T,i)*gamma_hat_k(i))
T_SPA = max(0, max_k(sqrt(T) * dbar_k / omega_hat_k))
```

Lacuna computes the autocovariances with an exactly zero-padded FFT and rejects non-positive or
non-finite long-run variance rather than silently dropping a candidate.

Hansen defines three null recenterings. Lacuna exposes all three:

```text
g_lower(x)      = max(0, x)
g_consistent(x) = x * 1{x >= -omega_hat * sqrt(2*log(log(T))/T)}
g_upper(x)      = x

Zbar_k*(b) = dbar_k*(b) - g(dbar_k)
T_SPA*(b) = max(0, max_k(sqrt(T) * Zbar_k*(b) / omega_hat_k))
```

The lower p-value is liberal, the upper is conservative, and the consistent p-value is the primary
reported decision value. All appear in metrics and the `p_values` table; each strategy's mean,
long-run variance, standardized mean, threshold, and three recenterings are separately inspectable.
Replicate `i` uses `SeedSequence([seed, 5, i])`.

SPA reduces the influence of poor high-variance alternatives; it does not authorize removing them
from the declared research family. Its validity still relies on a stationary, weakly dependent
differential process and a defensible common benchmark and block length.

## Validation and performance evidence

The v0.5 gate includes:

- exhaustive CPCV combination and complete-path invariants;
- generated no-overlap properties after CPCV purging;
- deterministic permutation-stream fixtures and fixed-seed null-size simulations;
- direct PSR/MinTRL moment-equation checks and complete-family DSR requirements;
- planted stable-edge and forced-selection-overfit PBO simulations;
- eager/lazy Polars, pandas, and Arrow equivalence for matrix inference;
- an independent literal implementation of White's bootstrap statistic;
- an independent direct-lag implementation of Hansen's long-run variance and all SPA recenterings;
- fixed-seed Reality Check/SPA null-size and planted-power simulations;
- a planted poor-model family demonstrating White's conservatism and SPA's intended robustness;
- benchmark artifact v5 cases retaining CPCV, PBO, Reality Check, and SPA coverage;
- clean-wheel smoke calls through the supported public API.

These are deterministic regression guardrails, not universal empirical validation. A method change
that alters values must update its `method_version`, the independent reference, simulations,
methodology, and release notes together.

## Primary references

- Bailey, Borwein, López de Prado, and Zhu, [*The Probability of Backtest Overfitting*](https://escholarship.org/uc/item/4w1110bb).
- Bailey and López de Prado, [*The Sharpe Ratio Efficient Frontier*](https://www.davidhbailey.com/dhbpapers/sharpe-frontier.pdf).
- Bailey and López de Prado, [*The Deflated Sharpe Ratio*](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).
- White, [*A Reality Check for Data Snooping*](https://doi.org/10.1111/1468-0262.00152).
- Hansen, [*A Test for Superior Predictive Ability*](https://doi.org/10.1198/073500105000000063).
- Politis and Romano, [*The Stationary Bootstrap*](https://doi.org/10.1080/01621459.1994.10476870).
