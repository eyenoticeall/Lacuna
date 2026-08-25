# Transaction costs, market impact, and capacity

**Status:** post-v0.1 subsystem. Interfaces should remain usable independently of any backtest engine.

This subsystem asks how fragile a strategy is to plausible trading friction. It does not claim to simulate an exchange.

## Ownership

`lacuna.costs` owns cost-model protocols, scenario evaluation, stress surfaces, break-even calculations, and capacity curves. It consumes normalized trades/positions and optional market data.

The subsystem does not route orders, maintain an order book, or hide a portfolio backtester inside cost analysis.

## Trade contract

Minimum trade fields:

```text
decision_time
execution_time
instrument
side
quantity
price
reference_price
```

Models request only additional fields they need, such as bid/ask, volume, ADV, volatility, borrow rate, or holding interval.

Side and quantity conventions are explicit. Recommended normalized signed quantity is positive for buy and negative for sell, while preserving original fields in provenance if converted.

## Cost model protocol

Target protocol:

```python
class CostModel(Protocol):
    name: str
    version: int

    def required_fields(self) -> tuple[str, ...]: ...
    def estimate(self, trades, market=None) -> CostEstimate: ...
```

`CostEstimate` includes per-trade components where feasible, aggregate totals, units, assumptions, excluded rows, and findings.

Models are pure for the same inputs/configuration. They do not read live market state.

## Units and signs

Internally distinguish:

- currency cost;
- basis points of notional;
- return drag;
- price impact;
- borrow rate per time unit.

Costs are non-negative magnitudes unless a model explicitly represents rebates. Net P&L subtracts cost exactly once. Conversion between units requires notional/capital context and appears in provenance.

## Built-in models

### Commission

Support fixed per order/trade, per unit/share, and percentage of notional. Minimum fee and currency handling are explicit.

### Spread

Half-spread assumes execution from mid to the relevant side. Full-spread may represent round-trip stress. If bid/ask is unavailable, a fixed-bps scenario is an assumption, not observed spread.

### Fixed or percentage slippage

Apply adverse price movement by side. A buy's execution price moves upward and a sell's downward. Tests verify sign symmetry.

### Volatility-scaled slippage

The model states volatility estimator, horizon, annualization, lag/availability, and coefficient. Same-period realized volatility cannot be used before available.

### Participation and square-root impact

A general square-root form may be:

```text
impact_fraction = coefficient × volatility × sqrt(abs(quantity) / volume)
```

The implementation defines volume horizon, cap/floor behavior, coefficient source, and whether impact is temporary or permanent. This is a scenario model, not universal market truth.

### Borrow cost

Borrow cost integrates an annualized rate over a short exposure interval and notional. Missing borrow availability/rate produces unknown evidence or an explicit conservative scenario.

## Composition

Composite models sum named components after validating compatible units and preventing duplicates. For example, a supplied execution price already containing slippage must not automatically receive the same slippage twice.

The result exposes each component separately.

## Stress surfaces

Target API:

```python
stress = lc.costs.stress(
    strategy,
    spread_bps=[0, 2, 5, 10, 20],
    slippage_bps=[0, 2, 5, 10],
)
```

The source table contains one row per scenario:

```text
scenario parameters
gross return / gross P&L
component costs
net return / net P&L
net Sharpe where defined
turnover and sample support
status/warnings
```

The implementation reuses path-independent sufficient statistics when valid. It must not reuse them for nonlinear/path-dependent models that require recomputation.

## Cost uncertainty

Scenarios may be a grid, discrete set, or sampled distribution. Correlated assumptions—such as wider spread during high volatility—must be representable.

Report parameter distributions and seeds. A single “base cost” is never presented as certain.

## Break-even cost

Break-even calculations solve for the all-in cost where a declared target crosses a threshold:

- expected alpha equals zero;
- Sharpe falls below a threshold;
- CAGR/return falls below a threshold.

The solver checks monotonicity over its domain, reports bracketing bounds and tolerance, and returns no solution when the target does not cross. It does not extrapolate silently.

## Capacity

Capacity is a curve over capital or trade size:

```text
capital
gross exposure/turnover
participation
spread/slippage/impact
net return
net Sharpe
constraint flags
```

Inputs include market volume, execution horizon, participation constraint, price/volatility, and capital-to-position scaling.

Do not reduce the curve to one capacity number without a declared objective and threshold. Missing liquidity data becomes unknown capacity evidence.

## Temporal correctness

Market fields used by a decision must be available by the modeled execution time. ADV and volatility estimates specify lag/window. Borrow rates and instrument eligibility are timestamped.

Cost analysis can be retrospective stress, but it must not be mislabeled point-in-time if it uses future realized liquidity.

## Invariants

For a path-independent model with non-negative components:

- increasing a cost parameter cannot increase net P&L;
- zero parameter produces zero component cost;
- scaling quantity by zero produces zero cost;
- buy/sell adverse slippage has symmetric magnitude under symmetric inputs;
- component sum equals total cost within numerical tolerance;
- gross P&L minus total cost equals net P&L exactly under declared units.

Nonlinear capacity models document where monotonicity should still hold.

## Execution ownership

Polars can own trade joins and scenario projections. Rust is suitable for large path-independent sweeps, grouped reductions, and capacity grids after benchmarking. Generic root finding or distributions should use mature numerical libraries.

## Required tests

- Hand-computed commission, spread, slippage, and borrow examples.
- Cost monotonicity property tests.
- Side/sign and unit conversion fixtures.
- Missing required market fields.
- No double application of supplied costs.
- Break-even bracketing, no-crossing, and tolerance behavior.
- Planted square-root impact curve.
- Point-in-time lag for liquidity estimates.
- Scenario determinism and component reconciliation.
- Native/reference differential and memory benchmarks for stress grids.
