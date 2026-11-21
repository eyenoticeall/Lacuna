# Changelog

## [0.2.2] - 2026-11-21

### Fixed

- `validate_chain` (and `empirical_residual`) now reject Decimal numeric columns with a
  `DataContractError` naming the column and dtype (`invalid dtypes: strike=Decimal(...)`) instead
  of leaking a raw Polars `InvalidOperationError`. Only float and integer columns are accepted;
  Decimal is not cast to Float64 because that would silently change quoted values.
- `delta_buckets` labels are always distinct for distinct edges. Labels keep two decimals (so
  existing outputs are unchanged) unless two edges would collapse at that precision, in which case
  all labels use the fewest decimals that separate every edge. Previously edges closer than 0.01
  shared a label and their `bucket_counts` and `occupied_buckets` were merged.
- `validate_chain` raises `DataContractError` when the input already has a `forward`,
  `time_to_expiry_years`, or `log_moneyness` column, `delta_buckets` raises when the chain already
  has `delta_bucket`, and `empirical_residual` raises `MethodContractError` when `output` equals
  `observed` or `expected`. Previously these columns were silently overwritten. Callers that re-validated a
  previously validated frame must drop the derived columns first.

### Documentation

- `OptionChain` and the subsystem guide now state that `validate_chain` is the validated entry
  point and that constructing `OptionChain(...)` directly performs no validation (behavior
  unchanged).
- The subsystem guide now describes the residual evidence the code produces (mean, median, RMSE,
  positive fraction, and `(time, underlying, expiration)` groups) and states that lazy frames are
  accepted and collected in full by `validate_chain`.

### Deferred

- Evidence results do not yet carry an `input_fingerprint`. A faithful fingerprint needs a
  timezone-portable, null- and dtype-explicit serialization of the source frame that the public
  `lacuna.experiment.fingerprint` does not provide (the core's helper for that is private), so it
  needs its own contract and method-version decision.

## [0.2.1] - 2026-08-28

### Changed

- Widen the core dependency to `lacuna-quant>=0.13,<0.15` after the v0.14 compatibility, clean
  wheel, and unchanged public-API gates passed. No options API or analytical behavior changes.

## [0.2.0] - 2026-08-27

### Changed

- Depend on `lacuna-quant>=0.13,<0.14`, preserving the `lacuna_options` import and the complete
  `0.1.x` public API while severing dependency resolution from the unrelated PyPI `lacuna` project.
- License future `lacuna-options` distributions under MIT only and include the MIT text in wheel
  and source archives. Previously published versions retain their original license grants.

## [0.1.6] - 2026-08-26

### Changed

- Expand the compatible core range to `lacuna>=0.5,<0.13` after the additive Lacuna `0.12`
  factor-panel interoperability milestone passed the unchanged extension API and joint-install
  gates.

## [0.1.5] - 2026-08-26

### Changed

- Expand the compatible core range to `lacuna>=0.5,<0.12` after the additive Lacuna `0.11`
  decay, diagnostic-projection, and event-study milestone passed the unchanged extension API,
  property, packaging, and joint-install gates.

## [0.1.4] - 2026-08-26

### Changed

- Expand the compatible core range to `lacuna>=0.5,<0.11` after the additive Lacuna `0.10`
  signal-transformation and evidence-rendering milestone passed the unchanged extension API,
  property, packaging, and joint-install gates.

## [0.1.3] - 2026-08-26

### Changed

- Expand the compatible core range to `lacuna>=0.5,<0.10` after the additive Lacuna `0.9`
  migration, diagnostics, benchmark, and reference-coverage release passed the unchanged extension
  API, property, coverage, profile-integration, packaging, and joint-install gates.

## [0.1.2] - 2026-08-26

### Changed

- Expand the compatible core range to `lacuna>=0.5,<0.9` after the additive Lacuna `0.8`
  standardized-audit release recognized real options evidence under the required options-profile
  capability and passed the unchanged extension API, property, coverage, and joint-install gates.

## [0.1.1] - 2026-08-26

### Changed

- Expand the compatible core range to `lacuna>=0.5,<0.8` after the additive Lacuna `0.7` bundle
  release passed the unchanged options API, property, coverage, and clean joint-install gates.

## [0.1.0] - 2026-08-26

### Added

- Add normalized option-chain validation with explicit quote, expiration, temporal, and optional
  field contracts.
- Add carry-based forward and log-forward-moneyness derivation under a declared year basis.
- Add deterministic absolute-delta buckets and empirical implied-volatility residual evidence.
