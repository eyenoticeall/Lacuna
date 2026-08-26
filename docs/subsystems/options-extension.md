# Options-research extension

**Status:** implemented as the separately versioned `lacuna-options` 0.1 package for the Lacuna
0.6 milestone. Patch `0.1.3` expands compatibility through additive Lacuna core `0.9.x`; it is
released beside core but is not a core dependency.

The extension provides empirical option-chain normalization and transparent derived coordinates.
It deliberately begins below the level of a pricing library: callers provide market/model fields,
and the extension validates their meaning before producing evidence.

## Package and compatibility boundary

The distribution and import names are distinct:

```text
distribution: lacuna-options
import:       lacuna_options
version:      0.1.x (independent of Lacuna core 0.9.x)
```

Install both artifacts from the same GitHub Release because the core distribution name on PyPI is
unrelated to this project:

```bash
python -m pip install \
  ./lacuna-0.9.0-cp311-abi3-<platform>.whl \
  ./lacuna_options-0.1.3-py3-none-any.whl
```

The extension supports `lacuna>=0.5,<0.10`. Its `0.1.x` exports and signatures are frozen in
`extensions/lacuna-options/tests/fixtures/public-api-v0.1.json`. Core and extension versions do not
advance in lockstep: a later extension patch can improve its own compatible contract without a core
release, while a future core incompatibility must update the dependency range and migration notes.

`0.1.3` changes only dependency metadata and integration evidence: core `0.9` is additive, the
extension's source/API contract is unchanged, and real validated-chain evidence continues through
the required standardized options-profile capability. The patch release is still required because
an installed distribution's dependency range is part of its compatibility contract.

Core remains importable without this package. Conversely, `lacuna_options` depends on the core data
boundary, exceptions, and evidence types instead of duplicating them.

## Normalized chain contract

`validate_chain(...)` accepts any eager table-like input supported by `lacuna.adapters.to_polars`.
The extension materializes globally because it validates cross-row and complete-column invariants;
its evidence records `materialized=True`.

Required canonical fields:

| Field | Contract |
| --- | --- |
| `time` | quote observation date/timestamp |
| `instrument` | stable option-contract identity |
| `underlying` | stable underlying identity |
| `expiration` | same physical Date/Datetime type and timezone as `time`; strictly later |
| `strike` | finite and strictly positive |
| `option_type` | exact lowercase `call` or `put` |
| `bid`, `ask` | finite, non-negative, and `bid <= ask` |
| `underlying_price` | finite and strictly positive |
| `rate`, `dividend` | finite continuously compounded annualized inputs supplied by the caller |

Optional fields:

| Field | Additional invariant |
| --- | --- |
| `mid` | finite and inside the inclusive bid/ask interval |
| `iv` | finite and strictly positive |
| `delta` | finite and in `[-1, 1]` |
| `gamma`, `vega` | finite and non-negative |
| `theta` | finite; sign is model convention and is not constrained |
| `open_interest`, `volume` | finite and non-negative |

All required fields reject nulls. Every numeric field present rejects null, NaN, and infinity. Empty
chains fail. The adapter preserves input order and extra columns; it neither deduplicates contracts
nor invents a sort order. Callers that require one quote per contract/time must establish that key
before using downstream research methods.

### Explicit vendor mapping

`columns` is a canonical-to-source mapping:

```python
chain = lo.validate_chain(
    quotes,
    columns={
        "time": "quote_timestamp",
        "instrument": "occ_symbol",
        "underlying": "root",
        "expiration": "expiry",
        "strike": "strike_price",
        "option_type": "right",
        "bid": "best_bid",
        "ask": "best_ask",
        "underlying_price": "spot",
        "rate": "continuous_rate",
        "dividend": "continuous_dividend_yield",
    },
)
```

Mappings must be one-to-one, use known canonical names, and may not overwrite an existing canonical
column. Lacuna does not infer whether a vendor's rate is simple, discrete, annualized, risk-free,
borrow-adjusted, or stale; map it only after resolving those semantics.

## Derived coordinates

When `mid` is absent, the extension computes the arithmetic quote midpoint:

\[
M = \frac{bid + ask}{2}.
\]

With quote time \(t\), expiration \(T_e\), declared day-count denominator \(B\), spot \(S\),
continuously compounded rate \(r\), and dividend yield \(q\):

\[
\tau = \frac{T_e-t}{B},\qquad
F = S\exp((r-q)\tau),\qquad
k = \log\left(\frac{K}{F}\right).
\]

The default `year_basis=365.25` is explicit evidence, not a claim about an exchange or model
convention. Date inputs use whole-day duration; Datetime inputs use total seconds. `forward`,
`time_to_expiry_years`, and `log_moneyness` must remain finite, with positive maturity and forward.

`OptionChain.evidence` identifies the mapping, source type, formulas, year basis, materialization,
whether midpoint was computed, and quote/instrument/underlying/expiration counts. Method identity is
`options.validate_chain`, version 1.

## Absolute-delta buckets

`delta_buckets(chain, edges=...)` requires a validated chain with `delta`. Boundaries must be a
strictly increasing finite one-dimensional sequence beginning at `0` and ending at `1`.

Buckets use absolute delta and are left-closed/right-open, except the final bucket is closed:

```text
[0.00,0.10) ... [0.90,1.00]
```

This convention assigns `|delta| == 1` exactly once and makes boundary behavior deterministic.
The returned `OptionFrameResult` adds `delta_bucket` and records edges, closure, coordinate, quote
count, occupied-bucket count, and bucket counts. It does not redefine a supplied delta model.

## Empirical surface residuals

`empirical_residual(chain, observed="iv", expected="expected_iv", output="iv_residual")`
computes:

\[
residual = observed - expected.
\]

Both inputs must exist, be finite numeric columns, and use distinct non-empty names; the output may
not overwrite an existing field. Evidence records the coordinate convention, field mapping,
residual mean/standard deviation/mean absolute value, and summaries by underlying and expiration.
The operation evaluates an already supplied expectation. It does not fit a surface or choose a fair
volatility model.

## Deliberate non-claims

The 0.1 extension does not provide or imply:

- a universal implied-volatility inversion;
- model-independent Greeks;
- American exercise, settlement, or dividend-event handling;
- SVI or another parametric surface fit;
- static-arbitrage detection or repair;
- realized-volatility alignment, delta hedging, or event-premium attribution;
- exchange calendar, symbology, or corporate-action normalization.

Those capabilities require explicit pricing model, exercise style, settlement, rate curve, dividend,
day-count, calendar, quote-quality, solver, and numerical convergence contracts. They should arrive
as separately versioned methods only after independent references and adversarial fixtures exist.

## Testing and release evidence

The extension gate includes:

- exact valid/invalid schema and mapping fixtures;
- Date, timezone-aware Datetime, expiration, quote, and finite-number boundaries;
- generated forward/moneyness and residual identities;
- bucket boundary and validation cases;
- an exact independent `0.1.x` export/signature fixture;
- strict typing, Ruff, and branch-aware coverage above 85%;
- isolated wheel installation beside the exact core wheel;
- wheel/sdist content verification, checksums, and release provenance.

Future pricing or calibration methods additionally need independent equation-level or trusted-library
comparisons, planted arbitrage violations, numerical convergence/failure evidence, and declared
tolerances. A high coverage percentage alone is not model validation.
