# Transaction costs, market impact, and capacity

**Status:** implemented for the v0.3 trading-realism milestone. Interfaces remain usable
independently of any backtest engine.

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

Implemented protocol:

```python
class CostModel(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> int: ...

    def required_fields(self) -> tuple[str, ...]: ...
    def estimate(self, trades, market=None) -> CostEstimate: ...
```

`CostEstimate` includes aligned per-trade components, complete and known-only totals, currency unit,
assumptions, explicit unknown rows, findings, and a stable input/configuration fingerprint.

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

Implemented API:

```python
stress = lc.costs.stress(
    trades,
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

The implementation validates the trade table once, evaluates each optional base model once, and
stores its values and explicit validity in a private contiguous component batch. It preaggregates
gross P&L, traded notional, base cost, and period totals before evaluating the grid. Scenario rows
therefore do not rebuild per-trade Python tuples or repeat Polars group-bys. Unknown-row eligibility,
component order, scenario order, and public evidence remain unchanged.

This reduction is valid for the implemented path-independent linear scenario terms. It does not
claim that a path-dependent execution simulation can use the same sufficient statistics.

## Cost uncertainty

Scenarios may be a Cartesian grid or an explicit discrete `CostScenario` set. The latter represents
correlated assumptions—such as wider spread together with higher slippage—without creating every
cross-product combination.

Sampled parameter distributions are not implemented in v0.3. A future randomized scenario method
must report its distribution and seed. A single “base cost” is never presented as certain.

## Break-even cost

Break-even calculations solve for the all-in cost where a declared target crosses a threshold:

- expected alpha equals zero;
- Sharpe falls below a threshold;
- CAGR/return falls below a threshold.

The solver checks monotonicity over its domain, reports bracketing bounds and tolerance, and returns no solution when the target does not cross. It does not extrapolate silently.

Gross P&L and traded notional are aggregated once. Net P&L and net-return evaluations are then
constant time per solver point. Sharpe and CAGR retain one ordered period vector and remain linear
in the number of periods, because those estimands genuinely depend on the return path.

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

For a capital scale `s`, the implementation applies the model's exact identities: participation,
gross P&L, spread, and linear slippage scale with `s`, while square-root impact cost scales with
`s^(3/2)`. Base period terms are aggregated once and reused over the scenario/capital grid. This is
an algebraic optimization of the existing model, not a change to its estimand.

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

Polars owns normalization/grouping and NumPy owns validated vector arithmetic. Lacuna v0.14 keeps
the public signatures and method versions unchanged while replacing repeated scenario rescans with
the sufficient-statistic reductions above. Independent literal-rescan fixtures remain in the test
suite. Private migration benchmarks include full public-call latency, result projection, process
RSS, and traced Python memory. A Rust reducer is considered only if these optimized references
remain material under the admission gate.

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
- Versioned end-to-end throughput, checksum, and memory benchmark for stress grids.
- Native/reference differential tests if and only if a native cost path is introduced.

The user-facing formulas, exact temporal policies, examples, and interpretation limits are in
[Trading costs, liquidity, and capacity](../methodology/trading-costs-capacity.md).
