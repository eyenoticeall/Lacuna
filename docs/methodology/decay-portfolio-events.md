# Decay inference, portfolio projections, and event response

This page defines the v0.11 mathematics shared by three diagnostic APIs. The methods answer distinct
questions and never substitute for one another.

## Positive exponential decay

For positive observation horizons `h`, Lacuna fits the direction-adjusted curve

```text
y(h) = amplitude × exp(-h / tau)
```

with `amplitude > 0` and `tau > 0`. The half-life is `tau × log(2)` trading observations. The fit is
descriptive evidence about a jointly aligned IC or spread curve, not a claim that alpha or portfolio
returns follow a physical exponential process.

Before fitting, every horizon must have observations for the same ordered periods. Stationary block
bootstrap samples those periods jointly across all horizons, preserving horizon dependence. A fit
is reportable only with at least four positive horizons, twenty common periods, positive
direction-adjusted means, convergence away from the upper bound, finite parameter intervals, and
the configured minimum coefficient of determination. Otherwise point and interval fields are
`null` with an explicit reason.

SciPy is imported only at the fitting call. The result records optimizer, bounds, SciPy version,
root entropy, deterministic substream derivation, resample count, expected block length, confidence,
fit residuals, and `R²`.

## Diagnostic projection accounting

Given requested gross exposure `G > 0` and net exposure `N` satisfying `|N| <= G`, leg magnitudes are

```text
long allocation  = (G + N) / 2
short allocation = (G - N) / 2
```

Long target weights sum to the positive long allocation. Short target weights sum to the negative
short allocation. Thus `G=1, N=0` means `+0.5/-0.5` and total absolute weight one.

Equal, rank, and absolute-signal schemes determine within-leg shares. Group-neutral projection first
allocates each leg equally across eligible joint groups, then applies the within-group scheme.
One-sided groups raise unless explicit exclusion is selected; retained group and leg weights are
renormalized and attrition is recorded.

For instrument `i` in observation cohort `t`, contribution is

```text
contribution[t, i] = target_weight[t, i] × forward_return[t, i]
```

The cohort return is the arithmetic sum of contributions. Concentration and implied one-way target
turnover are diagnostics over target weights. Cohort returns are never chained, and target weights
are not realized holdings.

## Event response bands

For event `e`, anchor price `P[e,0]`, and discrete offset `k`, raw response is

```text
response[e,k] = P[e,k] / P[e,0] - 1
```

The descriptive mean uses all observed event paths at each offset and reports its changing sample
count. Inferential input is the complete-offset subset so a bootstrap draw preserves path shape.
Pointwise limits are empirical bootstrap percentiles.

For simultaneous bands, each bootstrap curve is standardized by the bootstrap standard deviation
at each offset. The confidence critical value is the requested quantile of the maximum absolute
standardized deviation across offsets. The final band applies that one critical value to every
offset. Offsets with zero bootstrap deviation retain descriptive values but have `null` simultaneous
limits.

Pre-event diagnostics report the mean response and maximum absolute mean over negative offsets.
They identify visible pre-trends; they do not prove a causal violation without a declared event and
market model.
