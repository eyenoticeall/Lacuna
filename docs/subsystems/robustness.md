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
status
objective
sample count
warnings
runtime/fingerprint
```

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

Expose components:

- neighborhood median and dispersion;
- fraction positive/profitable;
- fraction passing a declared evidence threshold;
- local gradient and curvature where meaningful;
- peak isolation ratio;
- plateau width/connected component;
- rank persistence across folds or subperiods;
- failed/undefined neighborhood fraction.

An isolated-peak finding records the selected point, neighborhood definition, local summary, and threshold.

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
