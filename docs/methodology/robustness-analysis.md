# Parameter, temporal, and universe robustness

A successful point estimate is weak evidence. Lacuna v0.2 evaluates declared neighborhoods and
scenario sets while keeping failures, selection reuse, sample support, and composition changes
visible in structured tables.

## Parameter surfaces

`lacuna.validation.parameter_surface()` evaluates the complete Cartesian product of an ordered
parameter grid. Parameter names are canonicalized in sorted order; values retain their declared
order because adjacency depends on it. Duplicate canonical values, unordered candidate containers,
empty dimensions, and grids beyond `max_evaluations` are rejected before work begins.

```python
surface = lc.validation.parameter_surface(
    evaluate=evaluate_strategy,
    grid={"lookback": [40, 60, 80], "holding": [1, 5, 10]},
    objective="sharpe",
    evaluator_name="strategy.evaluate",
    sample_id="validation:2020-2024",
    selection_sample_id="training:2010-2019",
    selected_parameters={"lookback": 60, "holding": 5},
    code_id="git:abc123",
    registry=registry,
)
```

The evaluator receives one immutable-by-convention parameter mapping and must return an
`AnalysisResult` with a finite numeric objective metric. By default, ordinary evaluation exceptions
become failed surface points containing only the exception class. `failure_policy="raise"` instead
propagates the exception for debugging.

### Adjacency and isolation

Grid adjacency is Manhattan distance over declared dimension indices. For radius one, a point is a
neighbor when exactly one dimension moves by one declared step. Numeric magnitude is deliberately
irrelevant: adjacent categorical or irregularly spaced values are adjacent because the caller
declared their order.

For a selected objective \(s\), successful neighboring values, median \(m\), and median absolute
deviation \(d\), the isolation score is:

\[
I = \frac{s-m}{\max(d, |m|10^{-12}, \epsilon)}
\]

for maximization; minimization reverses the numerator. Fewer than two successful neighbors yields
`UNKNOWN`, not a fabricated stability pass. An isolation warning requires both a score at or above
`isolation_threshold` and a plateau width of one.

Plateau width is the connected component containing the selected point whose objectives are within
`plateau_tolerance × abs(selected objective)` in the favorable direction. A boundary finding records
dimensions where the selected point lies at an end of a non-singleton grid, because the search does
not bracket the apparent optimum.

If the function chooses the best point itself, the evaluation sample necessarily performed the
selection and receives `PARAMETER_SELECTION_REUSE`. Supplying an explicit point and a distinct
`selection_sample_id` records separation; identities are provenance claims, not proof that the
underlying samples are disjoint.

## Continuous perturbation

`lacuna.robustness.continuous_perturbation()` complements a grid with seeded draws around selected
numeric parameters. Each `PerturbationSpec` declares:

- `normal`: additive Gaussian shock with standard deviation `scale`;
- `lognormal`: multiplicative `exp(N(0, scale))` shock, requiring a positive center;
- `uniform`: additive shock in `[-scale, scale]`;
- optional inclusive lower/upper bounds;
- optional deterministic nearest-integer rounding.

```python
perturbed = lc.robustness.continuous_perturbation(
    evaluate_strategy,
    selected_parameters={"fast": 20, "slow": 100},
    perturbations={
        "fast": lc.robustness.PerturbationSpec(scale=3, lower=2, integer=True),
        "slow": lc.robustness.PerturbationSpec(
            distribution="lognormal", scale=0.15, lower=10, integer=True
        ),
    },
    constraint=lambda p: p["fast"] < p["slow"],
    constraint_name="fast_lt_slow:v1",
    objective="sharpe",
    evaluator_name="strategy.evaluate",
    sample_id="validation:2020-2024",
    code_id="git:abc123",
    draws=1_000,
    seed=42,
)
```

Opaque constraints cannot enter a stable fingerprint, so a callable constraint requires an explicit
versioned name. Bounds, false constraints, and constraint exceptions count as rejections. The result
reports attempted, accepted, rejected, successful, and failed counts plus a rejection table.
`max_attempts` bounds rejection sampling; exhaustion produces a failing shortfall finding rather
than silently returning the requested count.

The same seed and configuration generate the same accepted parameter sequence independently of
evaluation success. Reproducibility assumes deterministic evaluator behavior and an unchanged
NumPy generator/method version recorded in the result.

## Subperiod analysis

A `Subperiod` is a named half-open `[start, end)` window with a unique sample ID. Dates and aware
datetimes are supported; mixed or naive datetime boundaries are rejected. `subperiod_analysis()`
calls an evaluator for every declared window and extracts:

- the objective and required non-negative integer sample count;
- optional lower/upper confidence metrics;
- optional additive outcome such as P&L.

The result reports sign consistency, positive fraction, best/worst period, sample dispersion, linear
trend by declared period order, and the top share of absolute outcome. Overlapping windows are
allowed but explicitly warned because their metrics are dependent. Failed periods stay in the table.

The trend is descriptive: it treats declared order as equally spaced and is not a time-series model.
Absolute-outcome concentration remains defined when periods include losses; net-share language is
avoided because a near-zero net total is unstable.

## Universe perturbation

A `UniverseScenario` records a unique name, stable membership ID, eligibility `as_of` time, complete
instrument IDs, human-readable definition, and whether membership is point-in-time:

```python
from datetime import date

baseline = lc.robustness.UniverseScenario(
    "baseline",
    "membership:crsp:2024-01-02",
    date(2024, 1, 2),
    ("A", "B", "C"),
    "historically eligible common shares",
)
```

`universe_perturbation()` evaluates all scenarios and reports objective/sample support alongside:

- instrument count;
- retained baseline count and fraction;
- added and removed counts;
- Jaccard similarity to the baseline;
- maximum composition change across scenarios.

Instrument order is canonicalized because membership is a set, but duplicate identifiers are
rejected. A `point_in_time=True` flag is a recorded assertion, not independent proof of the source.
Any explicitly retrospective/current-only scenario produces a high-severity survivorship warning.

## Registry integration and limits

All three evaluator-based methods can append completed and failed executions to an
`ExperimentRegistry`. Data/sample, code, method, version, parameters, metric, result fingerprint,
and safe scenario metadata enter lineage. Constraint rejections are generator events rather than
executed trials; the seed and complete generator configuration reproduce them.

Robustness results remain conditional on the supplied evaluator, grid/distribution, periods, and
universes. They do not certify an omitted neighborhood, an inaccurate membership source, or an
unrecorded search.
