# Migrating factor research from Alphalens Reloaded

Lacuna can ingest the familiar date/asset factor panel and reproduce compatible descriptive
calculations when timing, groups, ties, and weights truly match. It does not emulate Alphalens as a
plotting facade or inherit its implicit calendar, filtering, portfolio, or inference choices.

This guide was reviewed against
[Alphalens Reloaded commit `f0a07c22`](https://github.com/stefan-jansen/alphalens-reloaded/tree/f0a07c22d554e4b4036983cc80320b432714fe7e).
The repository keeps a small attributed numerical fixture from that revision, but has no Alphalens
runtime dependency and copies no implementation.

## Convert a factor-data MultiIndex

Alphalens factor data commonly stores `date` and `asset` in a named pandas MultiIndex. Lacuna uses
columns internally, but only promotes index levels named by the explicit schema:

```python
from lacuna.adapters import FactorPanelSchema, FactorPanelSemantics, adapt_factor_panel

semantics = FactorPanelSemantics(
    signal_observation="close of session t",
    decision_time_rule="first tradable open after observation",
    forward_return_entry="next session open",
    forward_return_exit="close after the declared trading-observation horizon",
    horizon_clock="XNYS trading observations",
    timezone="America/New_York",
    calendar="XNYS",
    adjustment_policy="total-return adjusted",
    group_availability="available before the observation timestamp",
    imported_bucket_definition="Alphalens factor_quantile, five quantiles, no zero-aware split",
)

schema = FactorPanelSchema(
    schema_id="legacy-factor-data-v1",
    columns={
        "observation_time": "date",
        "instrument": "asset",
        "signal": "factor",
        "forward_return": "5D",
        "group": "group",
        "bucket": "factor_quantile",
    },
    semantics=semantics,
)

panel = adapt_factor_panel(factor_data, schema)
```

The adapter preserves extra columns and source row order. It does not sort, filter, join, bucket,
construct returns, or calculate statistics. Named index levels are not guessed: both the schema and
the pandas index must use the declared source names. Use `collect=False` to preserve a Polars lazy
input; pandas and Arrow edge objects normalize to an eager Polars frame.

When entry, exit, or availability timestamps are present, map them explicitly as `entry_time`,
`label_end`, and `available_time`. If the imported forward-return column does not carry those rows,
retain the semantic declaration but do not represent the data as though Lacuna had verified its
temporal construction.

## Analysis mapping

| Alphalens workflow | Lacuna workflow | Important boundary |
| --- | --- | --- |
| `factor_information_coefficient` | `lacuna.signal.ic` | Set `by` explicitly; overall and subgroup summaries are independent. |
| `mean_information_coefficient` | `ic` summary tables or an explicit aggregation of stored period IC | Frequency/calendar aggregation is never inferred. |
| `mean_return_by_quantile` | `bucketize` then `bucket_returns` | Bucket definition, ties, edge closure, and exclusions are evidence. |
| `quantile_turnover` | `turnover(..., lags=(1, ...))` | Lags are exact observation-index endpoints; gaps are not consecutive. |
| factor rank autocorrelation | `turnover` autocorrelation tables | Computed only on instruments present at both exact endpoints. |
| factor returns / factor weights | `portfolio_projection` | An explicit diagnostic cohort projection, never a backtest. |
| event return tables | `lacuna.events.event_windows` and `event_response` | Availability is the default anchor and dependence-aware inference is explicit. |
| tearsheet plots | `AuditReport.to_html(renderer="plotly", view="signal")` | Charts render retained evidence and never recompute statistics. |

An imported `factor_quantile` is preserved as `bucket`; Lacuna does not silently treat it as though
it came from `BucketSpec`. To obtain Lacuna's complete bucketing/attrition evidence, call
`bucketize` from the canonical signal instead of reusing the imported assignment.

## Grouped IC and availability

```python
result = lacuna.signal.ic(
    panel.frame,
    panel.frame,
    signal_time="observation_time",
    label_time="observation_time",
    by=("observation_time", "horizon", "group"),
    group_available_time="available_time",
)
```

This only applies when the panel actually maps the named horizon and availability columns. A group
label without timestamp evidence remains an unverified source declaration. A future-dated group
classification is rejected by the analytical method; an unknown availability policy produces an
`UNKNOWN` finding rather than an optimistic pass.

## Diagnostic portfolio exposure differs deliberately

Alphalens factor-return conventions may normalize long and short weights so their absolute values
sum to one within each side, producing 200% gross exposure when both legs are combined. Lacuna's
projection uses the portfolio-level definition:

```text
long allocation  = (gross_exposure + net_exposure) / 2
short allocation = (gross_exposure - net_exposure) / 2
```

Therefore `gross_exposure=1.0, net_exposure=0.0` allocates `+0.5` long and `-0.5` short. Request
`gross_exposure=2.0` only when 200% gross is intentional. Evidence reconciles each cohort's gross,
net, and leg exposures. The projection does not compound returns, resolve overlapping holdings,
manage cash, apply costs, or simulate execution.

## Deliberate non-equivalences

Lacuna does not implement Alphalens' lookahead z-score loss filtering. A filter whose threshold is
estimated from the full forward-return sample can use future observations to decide whether an
earlier row survives. Perform a temporally valid, documented preprocessing step outside the
adapter, then record its evidence and attrition.

Other defaults that must become declarations include:

- signal observation and decision timestamps;
- entry and exit price fields;
- trading versus calendar horizons;
- timezone, exchange calendar, and session rules;
- corporate-action and currency treatment;
- group availability and revision behavior;
- quantile count, split, ties, and out-of-range policy;
- weighting, demeaning, group neutrality, and gross exposure;
- uncertainty estimator, dependence unit, confidence, and random seed.

If any item is unknown, use the literal `"unknown"`. The adapter records an `UNKNOWN` finding and
downstream audits retain that uncertainty. This is intentional: container shape and index frequency
are not evidence that a research panel was decision-time safe.

## Compatibility fixtures

`tests/fixtures/alphalens-reloaded-f0a07c22.json` freezes the small IC fixture and expected values
from the reviewed revision. Tests exercise only the intersection where factor values, forward
returns, group membership, minimum group size, and Spearman semantics agree. Lacuna-specific
regressions separately cover differences in tie handling, exposure normalization, exact lag
endpoints, availability, and attrition. Compatibility never means that every Alphalens output is a
Lacuna correctness oracle.
