# Trading costs, liquidity, and capacity

Lacuna v0.3 asks a bounded question: how quickly does declared gross performance erode under
explicit trading-friction and liquidity assumptions? It does not reconstruct an order book, infer
fills, or claim that one impact formula describes every market.

## Normalized trade semantics

Every built-in model consumes the same semantic trade fields:

```text
decision_time · execution_time · instrument · side
quantity · price · reference_price
```

`decision_time` and `execution_time` use the same ordered dtype and satisfy
`decision_time <= execution_time`. Prices are positive finite values. Side is case-insensitive
`buy` or `sell`.

The default `quantity_convention="signed"` means buys are non-negative and sells are non-positive.
`"absolute"` accepts non-negative sizes and derives direction from `side`. Zero quantity is valid
and produces zero cost even for models with a fixed fee or minimum. `TradeColumns` maps different
physical names to these semantic roles without weakening the contract.

For trade (i), Lacuna defines monetary notional as:

\[
N_i = |q_i|p_i.
\]

Built-in costs are non-negative currency magnitudes. Net P&L is always gross P&L minus cost once.
Rebates, currency conversion, and signed cash flows are not inferred.

## Model estimates

Every built-in implements the runtime-checkable `CostModel` protocol:

```python
class CostModel(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> int: ...

    def required_fields(self) -> tuple[str, ...]: ...
    def estimate(self, trades, market=None) -> CostEstimate: ...
```

A `CostEstimate` retains every named per-trade component. A component value can be `None` when the
cost is genuinely unknown. `known_total_cost` sums only usable rows, while `total_cost` is `None` if
even one all-in row is unknown. This prevents a partial borrow or liquidity estimate from being
mistaken for a complete total. `to_result()` produces the shared immutable `AnalysisResult`
envelope with assumptions, findings, method version, input fingerprint, and a per-trade table.

`CompositeCostModel` requires unique component names, one currency, and equal row alignment. It
never performs implicit foreign-exchange conversion. Models reject an existing same-named cost
column unless the caller explicitly declares an incremental scenario. Spread and slippage models
also reject `price != reference_price` by default because observed execution prices may already
contain that friction; `allow_on_observed_execution=True` is an auditable opt-in to layer a further
stress.

## Commission

`CommissionModel` combines fixed, per-unit, and bps-of-notional charges:

\[
C_i = \max\left(C_{\min}, C_{\text{fixed}} + c_q|q_i|
      + N_i\frac{b}{10{,}000}\right)
\]

for nonzero trades. The fixed charge and minimum are both zero for a zero-size row. `notional_bps`
is a percentage commission, not a quoted bid/ask spread.

## Spread

`SpreadModel` accepts either observed `bid`/`ask` fields or an explicit
`quoted_spread_bps` assumption. The bps input is the full quoted bid/ask spread. With the default
half-spread mode:

\[
C_i^{\text{spread}} = N_i\frac{b}{2\times10{,}000}.
\]

Full-spread mode charges (N_i b/10{,}000), commonly as a conservative round-trip stress. For
observed quotes, the quoted fraction is `(ask - bid) / reference_price`; bid must be positive and
ask cannot be below bid. An assumed fixed spread is labeled as an assumption, not observed market
evidence.

## Slippage

`SlippageModel` combines an adverse fixed-per-unit charge and a proportional charge:

\[
C_i^{\text{slip}} = c_q|q_i| + N_i\frac{b}{10{,}000}.
\]

It represents magnitude rather than a fabricated fill price. Equal-size buys and sells therefore
have equal cost under symmetric inputs. `VolatilitySlippageModel` instead uses:

\[
C_i^{\text{vol-slip}} = N_i k\sigma_i.
\]

The caller declares the volatility column, estimator name, horizon, and optional availability-time
column. A value timestamped after execution is rejected; same-period realized volatility cannot be
silently treated as known in advance.

## Participation and impact

Participation is quantity divided by the declared volume horizon:

\[
\pi_i = \frac{|q_i|}{V_i}.
\]

`ParticipationImpactModel` implements the general power form

\[
I_i = k\sigma_i\pi_i^a,
\qquad C_i^{\text{impact}} = N_i I_i,
\]

where volatility is optional and defaults to one. `SquareRootImpactModel` fixes (a=1/2) and
requires both volume and volatility:

\[
I_i = k\sigma_i\sqrt{\pi_i}.
\]

The coefficient, volume horizon, volatility horizon, and optional impact cap are result
provenance. Impact is labeled temporary; the model makes no permanent-impact claim. A declared
participation limit produces a failing finding but does not silently clip size. An optional impact
cap does clip the scenario and produces a warning with the affected row count.

These formulas are scenario tools. Calibration error, intraday scheduling, venue selection,
cross-impact, crowding, market state, and order-book dynamics remain outside the estimate.

## Borrow

`BorrowCostModel` charges only short rows using an annualized decimal rate and explicit holding days:

\[
C_i^{\text{borrow}} = N_i r_i\frac{d_i}{D},
\]

where (D=365) by default. Long rows cost zero even when their borrow field is absent. For a short
with a missing, invalid, or not-yet-available rate, callers choose one declared policy:

- `"raise"` rejects the analysis;
- `"unknown"` keeps a `None` component and makes the complete total unknown;
- `"conservative"` applies an explicit non-negative fallback rate and emits a warning.

The conservative policy is a stress assumption, not repaired market data. Borrow availability,
instrument borrow eligibility, recalls, and locate constraints remain distinct evidence.

## Stress surfaces

`stress()` projects gross per-trade P&L across a Cartesian grid of quoted spread, slippage, and
commission assumptions:

```python
surface = lc.costs.stress(
    trades,
    gross_pnl="gross_pnl",
    spread_bps=(0, 2, 5, 10, 20),
    slippage_bps=(0, 2, 5, 10),
    commission_bps=(0,),
    capital=10_000_000,
    period="execution_time",
    annualization=252,
)
```

Each `stress_surface` row includes scenario parameters, gross P&L, every component total, complete
and known-only cost totals, net P&L/return, net Sharpe when defined, turnover, support, and status.
Quoted spread is charged as half-spread. Turnover and return require explicit capital; Sharpe also
requires an annualization factor and at least two nonconstant grouped periods.

Linear scenario values use one validated notional vector. Base `CostModel` estimates—such as borrow
or nonlinear impact—are computed once and reused across the path-independent grid. This reuse is
covered by an execution-count test and an end-to-end benchmark.

Correlated assumptions use explicit `CostScenario` values instead of a Cartesian grid:

```python
surface = lc.costs.stress(
    trades,
    scenarios=(
        lc.costs.CostScenario("calm", spread_bps=2, slippage_bps=1),
        lc.costs.CostScenario("volatile", spread_bps=12, slippage_bps=9),
    ),
)
```

Scenario names are unique and become table identities. The method is deterministic and samples no
unstated distribution.

## Break-even cost

`break_even_cost()` solves for the all-in bps-of-notional charge at which a declared metric falls to
a threshold. Supported metrics are `net_pnl`, `net_return`, `net_sharpe`, and `cagr`.

```python
break_even = lc.costs.break_even_cost(
    trades,
    metric="net_pnl",
    threshold=0,
    lower_bps=0,
    upper_bps=1_000,
    tolerance_bps=1e-6,
)
```

The solver first evaluates 33 evenly spaced domain points. If the target is not monotonically
decreasing, it returns `status="non_monotonic"` and no solution. If the threshold is not crossed,
it returns `status="no_crossing"`; it never extrapolates. A bracketed target uses bisection until
the declared bps tolerance or iteration limit. The complete check/bisection trace, bracket, status,
and tolerance remain in evidence.

Return and CAGR require capital. Sharpe and CAGR require annualization. Period P&L is grouped before
Sharpe or compound growth is calculated. A period return at or below -100% makes CAGR undefined
rather than producing a complex or misleading number.

## Liquidity diagnostics

`liquidity_diagnostics()` reports per-trade participation, data coverage, median/p95/maximum known
participation, and limit breaches. Invalid, missing, or future volume becomes `status="unknown"`,
not zero participation.

The required `classification_mode` prevents ambiguous temporal claims:

- `"point_in_time"` requires an `available_time` column and accepts a value only when it is no later
  than execution;
- `"retrospective"` permits hindsight liquidity evidence and always emits a warning.

Volume horizon and estimation lag are human-readable, nonempty provenance fields. They describe
the caller's market-data construction; Lacuna does not infer them from a column name such as `adv`.

## Capacity curves

`capacity_curve()` scales the supplied base quantities and gross P&L linearly from `base_capital`,
then applies half-spread, slippage, and square-root impact at every requested capital value and
`CapacityScenario`:

```python
curve = lc.costs.capacity_curve(
    trades,
    capital=(1_000_000, 5_000_000, 10_000_000),
    base_capital=1_000_000,
    scenarios=(
        lc.costs.CapacityScenario("low-impact", impact_coefficient=0.05),
        lc.costs.CapacityScenario("high-impact", impact_coefficient=0.20),
    ),
    classification_mode="point_in_time",
    available_time="market_available_time",
    max_participation=0.10,
)
```

The source table reports capital, scale, gross turnover/P&L, liquidity coverage, median/maximum
participation, breach count, each cost component, net P&L/return/Sharpe, and status. Capital must be
strictly increasing and scenarios must have unique names. Missing volume, volatility, or temporal
availability on a nonzero trade makes impact, total cost, and net evidence unknown for that curve;
known-only impact remains separately visible.

No scalar “capacity” is returned. Selecting one number requires an external declared objective and
threshold—such as minimum net return, maximum participation, or minimum liquidity coverage—and the
choice should remain research lineage. The curve is conditional on linear position/P&L scaling and
the supplied scenarios.

## Invariants and validation evidence

The v0.3 implementation is covered by:

- hand-computed commission, observed/assumed spread, slippage, borrow, and square-root impact cases;
- property tests for non-negative-cost monotonicity, buy/sell symmetry, component reconciliation,
  and impact monotonicity in trade size;
- missing-field, invalid-sign, timestamp, double-application, currency, and unknown-evidence tests;
- deterministic stress surfaces, planted break-even roots, no-crossing behavior, and tolerance;
- point-in-time liquidity coverage and planted nonlinear capacity erosion;
- eager/lazy Polars, pandas, and Arrow equivalence;
- a versioned full-call stress benchmark with output checksums, throughput, and traced memory.

The benchmark currently justifies the validated NumPy/Polars reference path. Lacuna has no native
cost kernel in v0.3, so there is no native/reference differential claim. A Rust sweep is appropriate
only after measured large-grid crossover evidence and must preserve these public results exactly.

## Interpretation limits

Results are conditional evidence, not execution forecasts. They cannot establish future spreads,
available borrow, feasible schedules, or market impact from an uncalibrated coefficient. Comparing
multiple named scenarios and preserving unknown rows is stronger evidence than selecting one
optimistic “base cost,” but scenario coverage is still the caller's responsibility.
