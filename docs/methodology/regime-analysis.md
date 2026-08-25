# Regime classification and conditional evidence

Regime analysis describes where an outcome occurs. It does not turn a volatility bucket or trend
label into a causal macro explanation. Lacuna v0.2 separates label construction from conditional
outcome analysis and requires point-in-time versus retrospective semantics to remain explicit.

## Quantile classifiers

`lacuna.regime.quantile_regimes()` consumes a unique time/scalar table and emits one row per time
with lower/upper thresholds, prior-history count, and regime label.

Four methods are supported:

| Method | Threshold source | Point-in-time interpretation |
| --- | --- | --- |
| `fixed` | caller-supplied ordered thresholds | safe if thresholds were genuinely fixed before use |
| `expanding` | all finite observations strictly before the row | trailing and future-excluding |
| `rolling` | at most `window` finite/prior positions | trailing and future-excluding |
| `retrospective` | full-sample quantiles | descriptive; earlier labels use later data |

Expanding and rolling methods shift the threshold history by one row. The current scalar never fits
its own thresholds. Until `min_history` finite prior observations exist, the row is `unknown` with
null thresholds. Missing/NaN source values also remain unknown; infinity is rejected.

```python
classified = lc.regime.quantile_regimes(
    volatility,
    time="time",
    value="realized_volatility",
    method="rolling",
    window=252,
    min_history=60,
    lower_quantile=0.25,
    upper_quantile=0.75,
    available_time="available_time",
)
```

Values at or below the lower threshold receive `low`; values at or above the upper threshold receive
`high`; other finite values receive `middle`. All four labels are configurable and must be unique.

An optional availability column must have the same physical time dtype as the observation time.
Rows where `available_time > time` produce a failing point-in-time finding. Absence of an
availability column does not alter threshold arithmetic; it limits what the provenance can prove.
Retrospective classification always carries a high-severity descriptive-only warning.

## User-defined regimes

Conditional analysis accepts any stable regime label table, not only quantile output. Users can
construct trend, implied-volatility, liquidity, dispersion, rates, drawdown, event, or composite
labels upstream. The contract is:

```text
time
regime
outcome
[available_time]
```

`classification_mode` is required. Use `point_in_time` only when label inputs and thresholds were
available at the observation. Use `retrospective` for full-sample descriptions.

## Conditional statistics

`lacuna.regime.regime_analysis()` keeps every label, including `unknown`, and reports for each:

- raw rows, finite outcome count, and excluded outcomes;
- mean and sample standard deviation;
- annualized Sharpe-like mean/standard-deviation ratio;
- hit rate;
- 95% normal confidence interval;
- total outcome and maximum cumulative drawdown;
- observation, net-outcome, and absolute-outcome shares;
- leave-one-regime-out total.

The v0.2 effective sample size uses positive lag-one autocorrelation:

\[
n_{eff} = \operatorname{clip}\left(\frac{n}{1 + 2\max(0, \rho_1)}, 1, n\right).
\]

The confidence interval is \(\bar{x} \pm 1.96s/\sqrt{n_{eff}}\). This compact estimator is not a
replacement for dependence-aware bootstrap inference. It is named in provenance so later methods
can change without silently reinterpreting stored evidence.

Groups below `min_observations` remain in the table and produce `UNKNOWN` evidence. A constant group
has no Sharpe value rather than infinite performance. Null/NaN outcomes are excluded and counted;
infinity is rejected.

## Concentration

Net outcome shares can be negative or exceed one when some regimes lose money. Lacuna therefore
uses absolute outcome contribution for its primary concentration warning:

\[
a_r = \frac{\sum_{t \in r}|x_t|}{\sum_t |x_t|}, \qquad
HHI = \sum_r a_r^2.
\]

The result records the top regime's absolute-outcome share beside its observation share. A warning
fires when the top absolute share reaches `concentration_threshold`. The conditional table contains
the source values for statements such as “67% of absolute outcome occurred in 17% of observations.”

Leave-one-regime-out total is the full net outcome less that regime's net outcome. It shows how much
aggregate outcome remains without each condition but is not an independently re-estimated strategy.

## Exclusive and overlapping labels

With `mutually_exclusive=True`, time keys must be unique. With `False`, `(time, regime)` pairs must be
unique but one time may have multiple labels. Overlap produces an explicit warning: row shares and
outcomes count label rows, so totals double-count observations across labels. HHI then describes the
provided label-row decomposition, not a partition of unique time.

## Failure interpretation

Regime evidence can be statistically correct but causally weak, retrospectively labeled, too small,
or dominated by one condition. Lacuna keeps these as separate findings. A point-in-time pass means
the supplied thresholds and availability timestamps do not show future use; it does not certify an
upstream feature whose own construction leaked future data.

