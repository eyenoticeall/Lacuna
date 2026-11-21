# Parameter, temporal, universe, and regime robustness

**Status:** the v0.2 parameter surface, continuous perturbation, subperiod, timestamped universe,
quantile-regime, and conditional-regime APIs are implemented. Specialized regime primitives,
distributed execution, and immutable evaluation caching remain later work.

Robustness asks whether evidence survives in a neighborhood of the selected research choice rather than at one optimized point.

## Ownership

- `lacuna.validation` owns parameter surfaces and multiple-testing correction.
- `lacuna.robustness` owns continuous, subperiod, and universe perturbation.
- `lacuna.regime` owns regime definitions and conditional evidence.
- universe/subperiod robustness consumes stable evaluation callbacks or precomputed result tables.
- audit rules interpret concentration and instability; domain functions compute them.

## Evaluation contract

A robustness evaluator is a deterministic callable over explicit configuration and data identity:

```python
def evaluate(parameters: Mapping[str, JsonValue]) -> AnalysisResult: ...
```

The evaluator declares:

- objective metric and direction;
- fixed versus perturbed inputs;
- sample and universe identity;
- seed behavior;
- failed/undefined evaluation policy;
- whether parameters affect label construction, model fitting, or portfolio transformation.

Do not cache callback results without a fingerprint covering inputs, code/method version, and effective parameters.

## Parameter surfaces

Implemented API:

```python
surface = lc.validation.parameter_surface(
    evaluate=my_strategy,
    grid={
        "lookback": range(40, 121, 5),
        "holding": [1, 3, 5, 10],
    },
    objective="sharpe",
    evaluator_name="strategy.evaluate",
    sample_id="validation:2020-2024",
    code_id="git:abc123",
)
```

The surface table contains one row per attempted point:

```text
parameter columns
point_id            (fingerprint of the point's parameters)
status
objective
error_category
warnings
grid_index          (ordered-grid indices)
```

The result also carries a `selected_neighborhood` table with the same columns. Per-point sample
count and runtime/fingerprint columns are planned and not emitted in v0.14.2.

Failed points remain visible. Silently dropping failures can make a boundary optimum look stable.

## Neighborhood definition

A neighborhood is defined before computing stability:

- adjacent grid cells;
- normalized Euclidean/Manhattan distance;
- per-parameter radius;
- domain-specific adjacency graph;
- random perturbation distribution.

Categorical and continuous parameters are not treated as the same distance without an explicit mapping.

## Stability components

Implemented in `validation.parameter_surface` (v0.14.2). Adjacency is fixed to
`ordered_grid_manhattan` over each parameter's declared ordered grid, with `neighborhood_radius`
grid steps; the other neighborhood definitions listed above are not implemented.

Emitted metrics:

- `neighbor_count` and `local_median` / `local_mad` (median and median absolute deviation of
  successful neighbors);
- `isolation_score`: the selected objective's gap to the neighborhood median, in units of the
  neighborhood MAD (floored away from zero), and `objective_to_local_median_ratio`;
- `plateau_width`: the number of grid points in the connected component (unit Manhattan steps) of
  points within `plateau_tolerance` (relative) of the selected objective;
- `neighbor_positive_fraction`, and `neighbor_passing_fraction` when `evidence_threshold` is given;
- `neighbor_failed_fraction`, `failed_points`, and `boundary_parameters` (dimensions where the
  selected point sits on the grid edge).

Emitted findings: `PARAMETER_ISOLATED_OPTIMUM` (warning when `isolation_score >=
isolation_threshold` and `plateau_width == 1`; records the isolation score, threshold, local
median/MAD, and plateau width), `PARAMETER_LOCAL_STABILITY`, `PARAMETER_ISOLATION_UNKNOWN` (fewer
than two successful neighbors), `PARAMETER_BOUNDARY_OPTIMUM`, `PARAMETER_SURFACE_FAILURES`,
`PARAMETER_SELECTION_SAMPLE_UNKNOWN`, `PARAMETER_SELECTION_REUSE`, and
`PARAMETER_SELECTION_SEPARATION`. The neighborhood definition is recorded in the result parameters.

Planned, not implemented: local gradient and curvature estimates, and rank persistence across folds
or subperiods. `subperiod_analysis` reports per-period metrics and does not compute rank persistence.

## Selection separation

The selected parameter and its neighborhood analysis must not reuse test data in a way described as out-of-sample evidence. Results distinguish:

- in-sample optimization surface;
- validation surface;
- final untouched test point/region.

If the same surface selected and evaluated the winner, the audit records selection bias rather than calling it independent robustness.

## Continuous perturbation

Random perturbations define distributions, bounds, transformations, and correlations. Examples:

- log-scale perturbation for positive parameters;
- integer rounding after sampling;
- constrained pairs such as fast window < slow window;
- correlated cost/volatility scenarios.

The v0.2 sampler draws declared parameter dimensions independently. Correlated scenario generators
remain a later extension and must record their covariance/correlation parameterization.

Record every attempted sample or a reproducible seed plus generator configuration. Rejection sampling reports rejection rate.

## Temporal stability

Subperiod analysis uses declared windows, not convenient retrospective slices. Outputs include each period's metric, sample support, confidence interval, and missing/undefined state.

Useful summaries:

- sign consistency;
- worst-period metric;
- dispersion and trend;
- fraction of total P&L/evidence by period;
- pre/post event sensitivity;
- rolling metric table.

Multiple overlapping windows require dependence-aware interpretation.

## Universe robustness

Universe perturbations can include:

- liquidity thresholds;
- market-cap thresholds;
- exchanges, countries, or sectors;
- minimum price;
- historical membership sources;
- deterministic random subsamples.

Every universe has a timestamped eligibility definition. Removing current failures using today's membership is survivorship bias, not robustness.

Outputs report retained instruments/observations and composition change alongside the research metric.

## Regime definitions

Regimes are timestamp-aligned classifications, not hard-coded macro stories.

Built-in primitives may cover trend, realized volatility, implied volatility, dispersion, rates trend, liquidity, and drawdown state. A regime provider returns:

```text
time
regime
[confidence/value/source]
```

The provider contract defines:

- source availability time;
- threshold fitting period;
- mutually exclusive versus overlapping labels;
- unknown/unclassified rows;
- look-ahead prevention;
- whether thresholds are fixed, expanding, or rolling.

A full-sample quantile used to label earlier “high volatility” periods is not point-in-time safe unless explicitly treated as retrospective descriptive analysis.

### Point-in-time findings (method version 2)

`quantile_regimes` keeps two claims separate for the `fixed`, `expanding`, and `rolling` methods:

- `REGIME_THRESHOLDS_POINT_IN_TIME` (`PASS`): the thresholds are caller-supplied or strictly
  trailing and are not fitted to the classified or later values. It says nothing about when the
  classified values were published.
- Source availability: without `available_time` the result carries
  `REGIME_SOURCE_AVAILABILITY_UNKNOWN` (`UNKNOWN`); with it, `REGIME_SOURCE_AVAILABLE` (`PASS`) or
  `REGIME_SOURCE_NOT_AVAILABLE` (`FAIL`, rows with `available_time > time`).

`regime_analysis` receives only a table, so `classification_mode` is a caller declaration that is
not checked against how the labels were built. The result records
`classification_provenance="declared_unverified"`, and a `point_in_time` result carries a warning
that labels and outcomes are paired on the same time key: Lacuna cannot verify that the outcome
starts after its label was available or that the label inputs were point-in-time. `regime_analysis`
does not yet accept a `quantile_regimes` result as input, so no cross-check of mode against label
provenance exists; that is open work. `quantile_regimes` is method version 2.

## Conditional evidence

For each regime, report:

- IC/spread or selected metric;
- return/Sharpe where supplied;
- drawdown and hit rate where meaningful;
- turnover;
- raw/effective sample size;
- confidence interval;
- fraction of total observations and outcome.

Small regimes remain visible with an insufficient-evidence state.

`regime_analysis` implements this for one supplied outcome column. Its `conditional_evidence` table
has `mean_outcome`, `standard_deviation`, `sharpe`, `hit_rate`, `maximum_drawdown`, `total_outcome`,
`sample_count`, `raw_observations`, `excluded_outcomes`, `effective_sample_size`, `confidence_lower`,
`confidence_upper`, `observation_share`, `net_outcome_share`, `absolute_outcome_share`, and
`leave_one_regime_out_total`. Per-regime turnover and per-regime IC/spread are not computed; pass a
precomputed per-period metric as the outcome to condition it on regimes.

## Concentration

Regime or temporal concentration quantifies dependence on a narrow subset. Potential components include:

- share of total P&L in each regime;
- share of absolute P&L;
- top-regime contribution versus observation share;
- Herfindahl-style concentration over non-overlapping regimes;
- leave-one-regime-out results.

The output must state how losses and overlapping regimes affect the measure. A sentence such as “72% of P&L occurred in 14% of observations” comes from source table values.

## Parallelism and caching

Parameter points, universes, subperiods, and regimes are natural parallel units. The planner must avoid nested Polars/Rayon/BLAS oversubscription.

Cache only immutable fingerprinted evaluations. Include evaluator/method version and relevant environment/configuration. A cache hit must be observable in diagnostics, not affect result semantics.

## Required tests

- Synthetic plateau versus planted isolated optimum.
- Boundary optimum and failed-neighbor handling.
- Distance/adjacency behavior for mixed parameter types.
- Same seed reproduces perturbations across threads.
- Selection and evaluation sample identities remain distinct.
- Planted regime dependence and regime concentration.
- No look-ahead in rolling/expanding regime thresholds.
- Universe composition and eligibility timestamps preserved.
- Small/unknown regime evidence remains explicit.
- Cache fingerprint changes with data, method, or parameter changes.

The v0.2 suite covers all items above except immutable evaluation caching, which remains unshipped;
its fingerprint requirement continues to constrain that later implementation.
