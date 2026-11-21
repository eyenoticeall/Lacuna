# Changelog

All notable changes to Lacuna will be documented here. The project intends to follow [Semantic Versioning](https://semver.org/) once its public release process begins.

## [0.14.2] - 2026-11-21

Corrections from a documentation-driven review of 0.14.1. Several entries change results or reject
inputs that were previously accepted; each names the method or rule version that identifies it.

### Fixed

- **Statistical correction:** the headline metrics of `signal.ic`, `signal.quantiles`, and
  `signal.bucket_returns` (method version 2) no longer pool horizons. With multi-horizon labels the
  IC summary, `mean_top_bottom_spread`, and the monotonicity metrics averaged every
  `(period, horizon)` row, mixing different estimands, and the headline monotonicity came from the
  first horizon in text order. They now describe one horizon: the first in a `LabelResult`'s
  declared order, recorded as `headline_horizon`, the same default `SignalStudy.audit` infers on. A
  bare multi-horizon label frame declares no order, so those metrics are null with an
  `IC_HEADLINE_HORIZON_UNDECLARED`, `BUCKET_HEADLINE_HORIZON_UNDECLARED`, or
  `QUANTILE_HEADLINE_HORIZON_UNDECLARED` finding (`UNKNOWN`). The headline never moves to a later
  horizon: when the declared one has no aligned rows its metrics are empty
  (`BUCKET_HEADLINE_HORIZON_EMPTY` for bucket returns). Per-horizon tables and single-horizon
  results are unchanged.
- `QUANTILE_MONOTONICITY` (rule version 2) scores the audit's `inference_horizon` row of the
  monotonicity table. It read the headline metric, which could belong to another horizon, and is
  now `UNKNOWN` for multi-horizon evidence without a matching `inference_horizon` policy.
- Horizon tables in `signal.ic`, `signal.quantiles`, `signal.bucket_returns`, and `signal.decay`
  are ordered by horizon length; as text, `"10D"` sorted before `"1D"` and `"5D"`.
- `signal.turnover` (method version 2) measures membership turnover on the balanced
  midpoint-position quantile sets that `quantiles` and `bucketize` use, recorded as
  `membership_bucket_rule`. It floored the rank, so a boundary instrument could sit in different
  buckets for returns and for turnover whenever the period size was not a multiple of the quantile
  count. Rank turnover and signal autocorrelation are unchanged. The midpoint rule keeps the top
  and bottom legs the same size; `quantiles` adopted it in 0.10.0 without a version bump or a
  methodology-doc update, which this release corrects.
- `SignalStudy(instrument=...)` with a non-default identifier column no longer breaks `ic`,
  `quantiles`, `bucket_returns`, `decay`, and `audit` with `missing required columns`. Label and
  bucket frames produced by Lacuna always carry the canonical `instrument` column; the join now
  reads it instead of the source name.
- `labels.forward_returns(missing="raise")` no longer rejects end-of-sample censoring, which made
  the policy fail on every finite panel. It still rejects null or NaN source prices and labels whose
  entry and exit observations exist without a defined return. Outputs of valid calls are unchanged.
  This replaces the documented rule that `"raise"` rejects any horizon censoring.
- `PURGED_VALIDATION_SUPPLIED` (rule version 2) accepts `cv.combinatorial_purged_kfold` evidence,
  and `SignalStudy.audit(split=...)` accepts a `CombinatorialSplitResult`. The rule is `UNKNOWN`
  without a purge count and `WARN` when the split purged nothing although the inference horizon's
  labels span two or more observations; only a split of non-overlapping sampled labels
  legitimately purges nothing there, and the rule cannot tell the two apart. A pass now records `data_identity_verified: false`: split
  evidence carries no input fingerprint, so the rule cannot verify the split came from the audited
  labels.
- `signal.ic` rejects infinite signal or label values on the declared inputs, including rows without
  a join partner; they previously passed uncounted.
- `signal.decay` (method version 2) names the spread period count in `ic_decay` `n_spread_periods`
  instead of the join-suffixed `n_periods_right`, and orders the table by horizon length.
- `validation.sharpe_inference` (method version 2) adds `DEFLATED_SHARPE_SUPPORTED` or
  `DEFLATED_SHARPE_UNCERTAIN` when `trial_sharpes` is supplied. The existing PSR finding ignored
  selection, so the best of many null strategies showed only a pass; it now records
  `selection_adjusted: false` and names the deflated finding to read with it.
- `validation.bootstrap(expected_block_length=0)` and negative values raise `MethodContractError`
  instead of silently using the default block length.
- `validation.multiple_testing` on an `ExperimentRegistry` applies the same `[0, 1]` p-value range
  and `null_policy` validation as array input.
- `validation.parameter_surface` raises `MethodContractError` when a `selection_sample_id` that
  differs from `sample_id` is given without `selected_parameters`, instead of discarding it.
- `PurgedKFold` validates `n_splits` and `embargo` types at construction like
  `CombinatorialPurgedKFold`; strings, floats, bools, and NumPy integers raise
  `MethodContractError`.
- `WalkForward` (method version 2) in calendar mode over `Date` times keeps a final window whose
  exclusive end is one day past the last observation, matching observation-count mode. `Datetime`
  behavior is unchanged.
- `bias.asof_join` validates `tolerance` against the time column's units before joining and raises
  `MethodContractError` instead of a Polars error or panic. Numeric tolerances on temporal columns,
  fractional tolerances on integer time, and calendar-variable or negative duration strings are
  rejected. String, categorical, and other unordered `revision` dtypes are rejected with
  `DataContractError` because they sort lexicographically. `future_matches` is computed from the
  joined output, and a warning states that `effective_time` does not affect matching.
- `bias.survivorship_diagnostics` (method version 2) reports `UNKNOWN`
  (`BIAS_SURVIVORSHIP_DELISTINGS_NOT_OBSERVED`) for a `confirmed_safe` source whose delisted column
  marks no row. `bias.universe_drift` (method version 2) reports `UNKNOWN`
  (`BIAS_UNIVERSE_DRIFT_UNDEFINED`) for universes with fewer than two snapshots, and `mean_drift`
  and `maximum_drift` are null instead of `0.0` when no transition exists.
- `regime.quantile_regimes` (method version 2) no longer implies source availability from fixed or
  trailing thresholds. `REGIME_THRESHOLDS_POINT_IN_TIME` covers threshold fitting only, and
  availability is reported separately as `REGIME_SOURCE_AVAILABILITY_UNKNOWN`,
  `REGIME_SOURCE_AVAILABLE`, or `REGIME_SOURCE_NOT_AVAILABLE`.
- `signal.neutralize(intercept=False)` (method version 2) keeps the full dummy set of the first
  categorical, so residuals are demeaned within every level; the first level was previously left
  un-demeaned. `GROUP_AVAILABILITY_UNKNOWN` names the exposure and group columns it concerns.
- `events.event_response` (method version 2) carries the supplied windows' `WARN`, `FAIL`, and
  `UNKNOWN` findings and records its clustering unit and overlap-cluster counts. The offset-0
  response of `events.event_windows` is exactly `0.0`.
- `events.event_response` and `signal.fit_decay` record a caller-supplied seed in `metadata.seed`.
- `lacuna signal` parses ISO date and datetime text in the declared time columns of CSV inputs;
  unparseable time text is a data-contract error.
- Vendor, backtest, and factor-panel adapters skip mapped optional columns that are absent from the
  data and record them as `absent_optional_columns` instead of raising a Polars error.
  Point-in-time and versioned vendor schemas reject a missing availability or revision column.
- `adapters.from_duckdb(collect=False)` raises `MethodContractError`; the Arrow stream is always
  materialized and the argument was silently ignored.

### Changed

- Adapter evidence records `source_type` with the public spelling (`polars.DataFrame`,
  `polars.LazyFrame`) used by the rest of the package.
- `costs.stress`, `costs.break_even_cost`, and `costs.capacity_curve` warn, whenever
  `annualization` is given, that Sharpe and CAGR use only periods containing a trade.
- `regime.regime_analysis` records `classification_provenance="declared_unverified"` and warns that
  a `point_in_time` mode is a caller declaration.
- `--no-color` is documented as a compatibility no-op; the CLI never emits color.
- Wheels no longer include the private `lacuna._migration_benchmark` module, which is release and
  CI tooling rather than runtime code. It remains in the repository and the source distribution.
  The corrections in this release took the wheel past the 20% growth limit against the v0.13
  baseline; removing the tooling keeps it inside that limit without changing the limit.

### Extension

- Publish `lacuna-options` 0.2.2 with its own corrections: Decimal columns are rejected with a
  contract error, close delta-bucket edges keep distinct labels, and derived or residual columns no
  longer overwrite same-named inputs. Its `lacuna-quant>=0.13,<0.15` range is unchanged.

### Documentation

- State that `SklearnCV` cannot check the row order of `X` and `y` against the split's data.
- State the forward-return `missing` policy, the stateless `BorrowCostModel` contract, the
  observed-spread divisor, walk-forward calendar coverage, as-of join `effective_time`, `revision`,
  and `tolerance` rules, the DSR threshold and findings, and the regime availability findings as
  implemented.
- Correct the glossary (ICIR, CPCV, stationary bootstrap, horizon units), the Alphalens migration
  guide, the parameter-stability outputs, bundle determinism and integrity wording, backend
  reproducibility claims, the `lc.audit` function-versus-module note, and the reserved
  `NativeExtensionError`.

## [0.14.1] - 2026-09-28

### Fixed

- **Statistical correction:** `SignalStudy.audit` no longer bootstraps every `(date, horizon)` IC
  row as one stationary series. Pooling mixed horizon estimands, and overlapping multi-period labels
  made adjacent IC values dependent, so an uninformative persistent signal excluded zero in about a
  quarter of null simulations and could earn `BOOTSTRAP_INTERVAL` `PASS`. The audit now infers on one
  declared horizon (the first study horizon, or `policies={"inference_horizon": ...}`) and resamples
  IID only periods whose label intervals are disjoint. `IC_DEFINED` and `IC_PERIOD_SUPPORT` (rule
  version 2) read that horizon's IC summary, and return `UNKNOWN` for multi-horizon IC evidence
  without a matching `inference_horizon` policy; `BOOTSTRAP_INTERVAL` (rule version 2) warns instead
  of passing below 30 resampled periods and is `UNKNOWN` without a sample count. Audits produced by
  0.14.0 and earlier remain identifiable by their recorded rule versions and should be regenerated.
- `labels.forward_returns` now rejects a horizon that exits at the entry observation from the same
  price field. Previously `entry="next_close"` with a `1D` horizon (including `SignalStudy`'s
  default horizons) silently emitted all-zero labels and an entirely undefined 1D IC. `next_close`
  requires horizons of at least `2D`; `next_open` with `1D` remains a valid open-to-close label.
  Valid label calls are unchanged, so the `labels.forward_returns` method version stays 1.
- `HORIZON_DECAY_COVERAGE` (rule version 2) counts only horizons whose `ic_decay` row has a
  defined mean IC and reports `n_defined_horizons` and `undefined_horizons`. Version 1 counted
  requested horizons, so a horizon with no defined IC period still earned a three-horizon `PASS`.
  Decay evidence without the per-horizon table now yields `UNKNOWN` instead of trusting the
  `n_horizons` count.
- `robustness.continuous_perturbation` now propagates constraint-callback exceptions under
  `failure_policy="raise"`, matching evaluator exceptions. They were previously always swallowed as
  `constraint_error` rejections, which hid a broken constraint behind an acceptance shortfall. The
  default `"record"` policy is unchanged.

### Tests and release QA

- Add fixed-seed null-calibration guards that run through `SignalStudy.audit`, and for block and
  within-date permutation, DSR selection deflation, and IID, circular, and stationary bootstrap
  coverage. Each guard pairs the method with the naive alternative it must beat.
- Cover every bundle-verifier hostile-archive, manifest trust-contract, digest, report-identity, and
  canonical-encoding rejection, and every vendor and backtest adapter declaration rejection.
- Record the intentional `study.audit` benchmark checksum change from the audit correction, with
  same-machine timing evidence, in the performance regression policy.

### Documentation

- Add theme-aware README lockup and footer-mark variants for GitHub, with baked-background
  fallbacks that remain legible when PyPI sanitizes responsive-image markup.
- Promote a PyPI-first **Get started** path near the top of the README, distinguish installed
  commands from repository `uv run` commands, and align the documentation landing and quickstart
  pages with the published `lacuna-quant` 0.13.0 and `lacuna-options` 0.2.0 releases.
- Use repository-absolute README assets and handbook links so future PyPI descriptions retain
  working brand imagery and navigation.
- Make the getting-started signal audit copy-pasteable and executable in CI; correct stale
  experiment-registry, IC-column, Alphalens grouping, and keyword-only API examples; and name
  `lacuna-quant` in current optional-dependency installation guidance and runtime errors.

## [0.14.0] - 2026-08-28

### Documentation and foundations

- Add an evidence-gated Rust migration candidate register covering native-boundary prerequisites,
  prioritized analytical kernels, explicit non-candidates, benchmark shapes, compatibility rules,
  and phased implementation order.
- Rectify the register into an admission-gated v0.14 program with terminal evidence states, a
  separate operational decision ledger, byte-identical c14n-v1 and public-carrier boundaries, and
  an accepted architecture decision preserving `abi3-py311`, Python-owned RNG, and single-threaded
  native execution.
- Add the private `lacuna.native-migration-benchmark` v1 sidecar, isolated alternating-backend
  runner, raw timing/RSS evidence, mechanical materiality and admission evaluator, clean-source
  enforcement, artifact validation, and deterministic correctness checks without changing the
  public benchmark-v6 API.
- Keep timed migration workers free of `tracemalloc` overhead and collect Python allocation and
  phase evidence once in a separate checksum-matched instrumented worker for each backend.
- Replace private per-element PyO3 conversions with checked, bulk NumPy carriers for grouped IC,
  bootstrap means, and interval purging; snapshot inputs before releasing the interpreter lock,
  return dense arrays plus byte validity/status codes, and preserve every public result contract.
- Add private immutable execution-budget resolution and make bootstrap honor scoped memory limits
  before allocating fixed output or batches, while retaining deterministic replicate substreams,
  the existing public signature, and single-threaded native execution.
- Stream c14n-v1 NumPy and Polars fingerprint inputs in bounded batches, preserving exact prefixes,
  digests, scalar normalization, sensitive-key rejection, row order, and chunk-layout invariance
  while removing whole-input `.tolist()` intermediates from inference fingerprints.

### Performance

- Add the admission-gated typed NumPy/PyO3 boundary and retain single-threaded native grouped-rank
  IC and PBO/CSCV dispatch only where full-call evidence clears the native gate.
- Replace repeated Python work in costs, capacity, break-even analysis, permutation testing, CPCV,
  bucketization, turnover, regime thresholds, event windows and response, diagnostic projection,
  universe transitions, and c14n-v1 fingerprints with exact NumPy or Polars references when Rust
  did not provide a justified end-to-end advantage.
- Add bounded execution-budget resolution, exact streaming c14n-v1 encoding, compact internal
  carriers, copy/workspace accounting, and deterministic backend-equivalence evidence without
  changing semantic fingerprints or randomized streams.

### Compatibility and release QA

- Preserve every v0.13 public signature, result table, method version, schema-v1 envelope,
  c14n-v1 digest, and public benchmark-v6 contract; add the cumulative v0.14 API fixture.
- Add authoritative isolated native-migration benchmarks, package/import regression gates,
  same-wheel `cp311-abi3` smoke on Python 3.11–3.14, target-wheel parity, nightly native property
  QA, and exact-source decision-ledger enforcement.
- Replace the yanked Polars 1.44.0 lock with 1.44.1 before regenerating authoritative evidence for
  the expression-heavy optimized paths.
- Add a non-publishing exact-SHA release rehearsal with checksummed preflight evidence. A tag must
  find that manifest, repeat all source, statistical, native, ABI, target-wheel, options, archive,
  and registry checks, then publish core before the independently versioned extension.
- Publish `lacuna-options` 0.2.1 with the unchanged API and a widened
  `lacuna-quant>=0.13,<0.15` dependency, verified against both supported core minor lines.

## [0.13.0] - 2026-08-27

### Changed

- Publish future core distributions under the unambiguous PyPI name `lacuna-quant` while
  preserving the `lacuna` import package and `lacuna` command.
- Split OIDC publication across protected `pypi` and `pypi-options` GitHub environments so each
  PyPI project has a unique trusted-publisher identity without storing registry credentials.
- Add an installation diagnostic that fails clearly when the conflicting `lacuna` distribution is
  installed beside `lacuna-quant`, preserving diagnostic schema and method version 1.
- License the repository and all future core and extension distributions under MIT only. Releases
  already published under the former dual-license terms retain those original grants.
- Advance `lacuna-options` to `0.2.0` so its dependency metadata targets
  `lacuna-quant>=0.13,<0.14` instead of the unrelated PyPI `lacuna` project; its import API and
  analytical semantics are unchanged.

## [0.12.0] - 2026-08-26

### Added

- Add immutable `FactorPanelSchema` and `FactorPanelSemantics` contracts plus
  `adapt_factor_panel()` for explicit generic Polars, Arrow, and optional named pandas MultiIndex
  ingestion without filtering, joining, bucketing, label construction, or statistical work.
- Add materialization/copy, source mapping, unknown-semantics, source-order, and no-methodology
  evidence for factor-panel adaptation.
- Add an Alphalens Reloaded migration guide and a small numerical IC fixture pinned and attributed
  to reviewed commit `f0a07c22`, with named tests for compatible and deliberately divergent cases.
- Add the cumulative `0.12.x` public API fixture while preserving every earlier compatibility
  contract and result schema version 1.

### Changed

- Advance the reproducible benchmark artifact to version 6 with grouped/null bucketing,
  neutralization, multi-lag turnover, diagnostic projection, event-window, and chunked factor-panel
  cases.
- Require zero skips in full-extra CI, exercise statistics/report/pandas wheels independently,
  render Plotly reports in the Chromium revision pinned by Playwright, enforce a same-runner 15%
  legacy median-regression budget, and run 500-simulation event/decay calibration for nightly and
  tagged releases.

### Fixed

- Map corrupt ZIP member reads during reproducibility-bundle verification to a concise
  `ReportError`, so `lacuna bundle verify` rejects damaged archives without exposing a Python
  traceback.

## [0.11.0] - 2026-08-26

### Added

- Add `fit_decay()` with positive constrained exponential fitting, joint-period stationary block
  bootstrap, explicit identifiability gates, deterministic RNG provenance, and use-site optional
  SciPy through `lacuna[statistics]`.
- Add immutable `PortfolioProjectionResult` and explicit gross/net, leg, weighting, group-neutral,
  contribution, concentration, coverage, attrition, and target-turnover evidence without portfolio
  compounding or execution simulation.
- Add `lacuna.events` with availability-default event anchors, next-observation alignment, window
  censoring and overlap evidence, and complete-path anchor-cluster stationary-bootstrap pointwise
  and simultaneous response bands.
- Add ADR-015, the event-study subsystem contract, the shared v0.11 methodology, and the cumulative
  `0.11.x` public API fixture.

### Changed

- Retain jointly aligned period/horizon IC and spread tables in descriptive decay evidence so
  inference resamples each period across all horizons without recomputation.
- Extend interactive reports with stored decay-fit, portfolio-cohort, and event-response panels.

## [0.10.0] - 2026-08-26

### Added

- Add immutable `BucketSpec` and `SignalTransformResult` APIs for balanced or tie-preserving
  quantiles, split-aware quantiles, equal-width buckets, explicit edges, thresholds, and visible
  exclusion policy.
- Add availability-aware grouped IC/bucket evidence and float64 weighted least-squares signal
  neutralization with deterministic categorical encoding and rank/fit diagnostics.
- Add standardized `data_attrition` tables to labels and touched signal methods, plus exact
  multi-lag rank, autocorrelation, and all-bucket membership turnover while preserving lag-one
  outputs.
- Add immutable named evidence to `AuditReport`, study evidence retention and bundle inclusion, and
  a deterministic self-contained Plotly renderer over stored evidence through `lacuna[report]`.
- Add the cumulative `0.10.x` public API contract and make historical signature checks accept only
  additive optional keyword parameters.

### Changed

- Extend `SignalStudy` with explicit bucket, neutralization, grouping, multi-lag, and caller-evidence
  delegation while preserving the functional APIs as the analytical source of truth.

## [0.9.0] - 2026-08-26

### Added

- Add a published persisted-artifact compatibility matrix and tagged-fixture regression corpus for
  result schema v1 across core `0.1`–`0.8`, bundle v1 across `0.7`–`0.8`, and standardized audit
  profile v1 from `0.8`.
- Add strict non-executing `AuditProfile.from_dict(...)` / `from_json(...)` and standalone
  `BundleManifest.from_dict(...)` / `from_json(...)` readers with fail-closed version, field,
  duplicate-key, non-finite, and nested-contract validation.
- Add a versioned public installation-diagnostics API and `lacuna doctor --strict` gate with stable
  check codes for package/native identity, Python and wheel support, dependency metadata, packaged
  schemas, and runtime configuration; diagnostics redact configured paths and never inspect user
  data or activate plugins.
- Advance the deterministic benchmark artifact to version 5 with an integrated strategy-audit case
  spanning labels, signal IC, purged validation, stationary bootstrap, cost stress, point-in-time
  data, vendor/backtest adapters, and standardized-audit composition; publish the initial profile
  and retain production behavior because it found no justified semantic-preserving optimization.
- Add a complete Python API surface reference and versioned coverage manifest; contract tests now
  require every cumulative root/module export, compatibility fixture, human symbol section, and
  semantic design route to agree exactly.

### Changed

- Advance `lacuna-options` to `0.1.3` only to widen its compatible core range to
  `lacuna>=0.5,<0.10`; its independent `0.1.x` Python API and analytical semantics are unchanged.
- Complete the internal `0.9` roadmap boundary and v1 ledger audit. Every internal v1 definition
  item now has released or release-gated evidence; `1.0.0` remains blocked by the explicitly
  external requirement for real users applying Lacuna to independent research stacks.

### Fixed

- Pin repository JSON artifacts to LF checkouts so persisted-fixture SHA-256 and Git blob identities
  remain byte-stable on Windows as well as Linux and macOS.

## [0.8.0] - 2026-08-26

### Added

- Add versioned standardized audit profiles for signal, strategy, and options research scopes over
  every released analytical, adapter, plugin, and extension method family.
- Add explicit required, optional, and not-applicable capability coverage; category, requirement,
  inventory, and domain-finding evidence tables; and unchanged propagation of source findings.
- Add a published standardized-audit profile v1 JSON Schema, frozen strategy/profile and additive
  `0.8.x` public API fixtures, plus real options-extension profile integration.
- Add strict `AnalysisResult.from_dict(...)` and `from_json(...)` readers with duplicate-key,
  non-finite, schema, field, enum, timestamp, and version rejection.
- Add `lacuna audit --scope ... --evidence NAME=PATH` with bounded named evidence, deterministic
  bundle output, safe overwrite behavior, and existing finding-based exit policies.
- Add an executable vendor/backtester-to-audit example and installed-wheel standardized-audit,
  strict-reader, schema-resource, and bundle coverage.

### Changed

- Render standardized reports as categorical evidence assessments with required/optional coverage
  and no universal cross-phase strategy-quality score; the frozen v0.1 signal score is unchanged.
- Advance `lacuna-options` to `0.1.2` only to widen its compatible core range to
  `lacuna>=0.5,<0.9`; its independent `0.1.x` public API remains unchanged.
- Publish the standardized-audit reference, ADR-014, profile-specific agent review workflow, and an
  updated v1 ledger that leaves migration/operational hardening and independent real-user evidence
  as the remaining pre-v1 work.

## [0.7.0] - 2026-08-26

### Added

- Add deterministic `.lacuna` reproducibility bundles containing the canonical audit,
  Markdown/HTML projections, resolved configuration/environment summaries, and optional structured
  evidence, provenance, and invocation metadata.
- Add a published bundle-manifest v1 JSON Schema, frozen additive `0.7.x` API fixture, SHA-256
  artifact-set/member verification, and Python plus CLI creation/verification workflows.
- Add bounded hostile-archive validation, supplemental secret/URL/path redaction, fail-closed
  canonical evidence checks, and explicit integrity-versus-authenticity semantics.

### Changed

- Extend clean-wheel smoke and release archive inspection to require the bundle module, installed
  manifest schema, and an end-to-end bundle create/verify path.
- Publish the reproducibility-bundle contract, v1-readiness ledger, architectural trust decision,
  migration boundary, and `0.8`/`0.9` candidate hardening scopes.

### Fixed

- Escape source-derived HTML metacharacters in Markdown reports so a downstream Markdown renderer
  cannot interpret hostile finding text as embedded HTML.

## [0.6.0] - 2026-08-26

### Added

- Add DuckDB Arrow-stream ingestion without pandas or SQL construction, and a dependency-free
  scikit-learn bridge over frozen walk-forward, purged, and combinatorial temporal folds.
- Add immutable vendor schemas with explicit availability, revision, timezone, adjustment, and
  identifier declarations, plus generic return/trade/position adapters that require complete
  backtest semantics.
- Add domain-specific Python entry-point groups, metadata-only discovery, deterministic conflict
  selection, explicit trusted-code activation, and protocol-major/capability negotiation with
  structured evidence.
- Add the independently versioned `lacuna-options` 0.1 distribution with normalized empirical
  chains, carry forwards, log-forward moneyness, deterministic delta buckets, and supplied-model IV
  residual evidence.
- Freeze additive core `0.6.x` and independent extension `0.1.x` public export/signature fixtures,
  and add real DuckDB/scikit-learn integration plus options property/adversarial tests.

### Changed

- Extend CI, clean-wheel smoke testing, release-set inspection, checksums, and provenance to cover
  the separately built options wheel/source distribution without adding core runtime dependencies.
- Publish the Phase 8 adapter, plugin, options, package-version, security, testing, and post-phase
  integration contracts throughout the developer and agent handbook.

## [0.5.0] - 2026-08-26

### Added

- Add combinatorial purged K-fold over every held-out group combination, with half-open interval
  purging, embargo after every test group, explicit combinatorial safety limits, visible group/fold
  tables, and deterministic complete-path reconstruction.
- Add unrestricted, within-date, within-group, block, and sign-flip permutation schemes with
  explicit null contracts, alternatives, deterministic per-replicate streams, and finite-resample
  p-value correction.
- Add non-Normal-return Sharpe uncertainty, two-sided confidence bounds, Probabilistic Sharpe Ratio,
  minimum track-record length, and Deflated Sharpe Ratio over a visible complete trial family and
  declared effective independent-trial count.
- Add symmetric CSCV/PBO over synchronous strategy matrices with complete IS/OOS selection evidence,
  average OOS ranks, logits, deterministic tie policy, partition sensitivity, and bounded
  combination enumeration.
- Add joint stationary bootstrap that shares one index path across strategy columns and reports
  per-strategy means, standard errors, and long-run covariance evidence.
- Add White Reality Check with joint stationary resampling and Hansen SPA with studentization,
  the stationary-bootstrap population long-run variance kernel, and separately exposed lower,
  consistent, and upper null recenterings.
- Add literal equation-level White/Hansen references, deterministic stream fixtures, CPCV/PBO
  properties, adapter equivalence, and fixed-seed permutation, Sharpe, PBO, Reality Check, and SPA
  simulation suites.
- Publish a comprehensive advanced-inference methodology and agent review contract, and freeze the
  additive `0.5.x` public API while preserving executable `0.1.x` through `0.4.x` contracts.

### Changed

- Complete roadmap Phase 7 and designate separately optional adapters and extensions as the next
  `0.6.x` milestone.
- Advance the reproducible benchmark artifact to version 4 with public CPCV, PBO, Reality Check,
  and SPA reference cases, stable checksums, workload-specific throughput, and traced memory.
- Require the advanced-inference implementation, CV surface, and validation surface in source and
  wheel distributions, and exercise CPCV/PBO/permutation/Sharpe/Reality Check/SPA in clean-wheel
  smoke tests.

### Fixed

- Use the declared two-sided confidence level for Sharpe confidence bounds while retaining the
  one-sided confidence quantile for PSR and minimum track-record decisions.
- Reject permutation-invariant mean statistics for reorder-only permutation schemes, ambiguous PBO
  partition types, non-numeric DSR trial families, and invalid CPCV integer configuration early with
  domain-specific errors.

## [0.4.0] - 2026-08-26

### Added

- Add deterministic point-in-time as-of joins with explicit decision/availability semantics,
  identity matching, exact-boundary and staleness policies, stable left order, explicit unmatched
  handling, revision-tie resolution, and a verified zero-future-match invariant.
- Add direct future-data diagnostics with missing-availability preservation, equal-boundary counts,
  bounded affected-row evidence, and optional absolute materiality.
- Add structural revision-history diagnostics with unique version identities, monotone publication
  ordering, per-fact version summaries, and explicit point-in-time/latest-only/unknown source modes.
- Add three-state survivorship evidence, planted delisting support, half-open membership interval
  validation, overlap and late-availability detection, and no unknown-to-pass conversion.
- Add availability-safe historical membership selection that rejects ambiguous interval sources and
  visibly excludes otherwise-active rows that were not yet observable.
- Add consecutive universe additions, removals, retention, Jaccard similarity, and drift evidence
  with explicit source survivorship status.
- Add reusable `DatasetSpec` contracts and structured validation for required fields, empty inputs,
  null constraints, key uniqueness, numeric/temporal dtypes, non-finite values, and temporal order.
- Add exact temporal/revision/survivorship fixtures, generated latest-nonfuture and half-open
  interval invariants, and eager/lazy Polars, pandas, and Arrow equivalence.
- Publish a complete point-in-time data-correctness methodology guide and freeze the additive
  `0.4.x` public API while preserving executable `0.1.x` through `0.3.x` contracts.

### Changed

- Complete roadmap Phase 6 and designate advanced inference as the next guarded milestone.
- Advance the reproducible benchmark artifact to version 3 with a public point-in-time as-of case,
  deterministic checksum, left-row throughput, and traced-memory evidence.
- Require `lacuna.bias` in wheel/source distributions and exercise the availability firewall in
  clean-wheel smoke tests.

## [0.3.0] - 2026-08-26

### Added

- Add a runtime-checkable cost-model protocol, configurable normalized trade columns, and immutable
  `CostEstimate` values with named per-trade components, complete/known-only totals, explicit
  unknown rows, assumptions, findings, units, and stable fingerprints.
- Add fixed/per-unit/notional commission, observed or assumed half/full spread, fixed/proportional
  slippage, volatility-scaled slippage, general participation impact, square-root impact, and
  annualized borrow models.
- Add component composition with strict row/currency/name reconciliation and safeguards against
  silently applying costs again to observed execution prices or existing component columns.
- Add deterministic Cartesian cost grids and explicit correlated `CostScenario` sets with gross/net
  P&L, return, Sharpe, turnover, component reconciliation, support, and unknown-cost status.
- Add monotonicity-checked, bracketed all-in-cost break-even solving for net P&L, net return, net
  Sharpe, and CAGR, including complete solver traces and no silent extrapolation.
- Add point-in-time or explicitly retrospective liquidity diagnostics with participation coverage,
  distribution summaries, constraints, and unknown/future-volume evidence.
- Add multi-scenario square-root-impact capacity curves across strictly increasing capital values,
  including liquidity coverage, participation, component costs, net performance, and constraint
  status without inventing one capacity number.
- Add hand-computed, property, planted, temporal, missing-data, component, adapter, packaging-smoke,
  and frozen `0.3.x` public API contract tests while preserving the `0.1.x` and `0.2.x` contracts.
- Add a complete trading-cost/capacity methodology guide and promote the subsystem architecture from
  target design to implemented behavior.

### Changed

- Advance the implementation roadmap through Phase 5 and designate point-in-time data correctness
  as the next milestone for the `0.4.x` series.
- Reuse validated path-independent sufficient statistics and one-time base-model estimates across
  stress surfaces.
- Advance the reproducible benchmark artifact to version 2 with a nine-point public cost-stress
  case measuring scenario throughput, output equivalence checksum, and traced memory.
- Require `lacuna.costs` in wheels/source distributions and exercise a cost surface in clean-wheel
  smoke tests.

## [0.2.0] - 2026-08-26

### Added

- Add versioned canonical JSON and SHA-256 research identities with rejection of ambiguous,
  non-finite, timezone-naive, callable, unordered, and credential-bearing values.
- Add an append-only SQLite experiment registry for completed, failed, cancelled, retried, and
  explicitly superseding attempts, plus full eligible-set selection lineage and structured registry
  snapshots.
- Add Bonferroni, Holm, Benjamini-Hochberg, and Benjamini-Yekutieli multiple-testing corrections
  over explicit trial families or current registry attempts.
- Add deterministic parameter-surface evaluation with failed-point visibility, local neighborhoods,
  peak isolation, plateau width, grid-boundary evidence, threshold support, and selection/evaluation
  sample separation.
- Add seeded continuous parameter perturbation with normal, lognormal, and uniform distributions,
  bounds, integer rounding, named constraints, rejection accounting, attempt budgets, and registry
  integration.
- Add declared half-open subperiod analysis with sample support, confidence interval passthrough,
  overlap warnings, sign consistency, dispersion, trend, failures, and outcome concentration.
- Add timestamped universe perturbation with stable membership identities, complete instrument sets,
  retained-baseline fractions, composition Jaccard distance, sample support, and explicit
  retrospective-membership findings.
- Add fixed, strictly trailing expanding/rolling, and explicitly retrospective quantile regime
  classifiers with source-availability validation and unknown-history states.
- Add conditional regime evidence with raw/effective sample size, confidence intervals, Sharpe,
  hit rate, drawdown, net/absolute contribution, leave-one-regime-out totals, overlap semantics, and
  concentration findings.
- Publish and regression-test the additive `0.2.x` public API contract while continuing to test
  preservation of the `0.1.x` contract.

### Changed

- Advance the implementation roadmap through Phase 4 and designate trading realism as the next
  milestone for the `0.3.x` series.
- Make release-contract verification select the public API fixture for the release's major/minor
  series and require new Phase 4 modules in wheels and source distributions.

## [0.1.0] - 2026-08-26

### Changed

- Promote the fully verified `0.1.0-rc.1` implementation and its frozen `0.1.x` public contract to
  Lacuna's initial stable release.
- Publish stable version tags as GitHub Releases while retaining prerelease treatment for SemVer
  candidate tags.
- Record the maintainer decision to waive independent-user acceptance for `0.1.0` because no testers
  were available; this release makes no claim of external user validation.

### Removed

- Retire the candidate-specific acceptance protocol and public validation tracker references.

## [0.1.0-rc.1] - 2026-08-26

### Added

- Initial mixed Python/Rust project scaffold.
- Typed configuration, finding, provenance, and analysis result contracts.
- Polars-first dataframe normalization boundary.
- Native bridge diagnostics and checked numerical smoke kernel.
- Unit, property, integration, Rust, and CI test foundations.
- Initial project documentation and branding.
- Comprehensive developer handbook, subsystem architecture contracts, reference material, and coding-agent playbooks derived from the technical specification.
- Forward-return labels, Pearson/Spearman IC, quantile diagnostics, turnover, decay, and native grouped-rank, bootstrap-reduction, and interval-purge kernels.
- Expanding and rolling walk-forward splits, interval-aware purged K-fold with embargo, and deterministic IID, moving, circular, and stationary bootstrap inference.
- Versioned audit rules and scoring with explicit unknown/not-applicable evidence, deterministic JSON/Markdown/self-contained HTML reports, a functional audit API, the `SignalStudy` workflow, and the `lacuna signal` CLI.
- Published audit-result JSON Schema and golden fixtures, plus pandas/Arrow/lazy adapter equivalence, SciPy reference checks, and randomized native differential/property suites.
- Reproducible Python end-to-end and Criterion Rust benchmark suites with deterministic generators, equivalence checksums, throughput, memory evidence, and smoke/small/medium dataset tiers.
- Complete v0.1 methodology documentation, executable signal/purging examples, corrected implementation status, and a packaged copy of the published audit-result schema.
- Add strict documentation and clean source-distribution/wheel smoke jobs to CI.
- Redesign CI as a staged, cross-platform gate with frozen installs, immutable action pins, coverage,
  retained evidence, Dependabot maintenance, and a stable branch-protection result.
- Add conservative adapter-copy/materialization provenance and execution-operation diagnostics to
  analytical input evidence.
- Validate signal, label, and price time/identity schemas, external label intervals, delisting-return
  dtypes, key compatibility, and runtime policy values before analytical execution.
- Freeze the `0.1.x` root/module export surface and primary call signatures in an executable public
  API contract with documented compatibility and migration rules.
- Build tagged CPython 3.11 stable-ABI wheels for Linux x86_64/aarch64, macOS arm64, and Windows
  x86_64; smoke-test each target artifact, validate the complete distribution set, publish checksums,
  and generate GitHub provenance before creating a prerelease.
- Add an independent-user release-candidate protocol and structured feedback issue form with explicit
  acceptance criteria and a non-fabricated evidence register.
- Keep RC1 registry publication disabled because the PyPI `lacuna` distribution is owned by an
  unrelated project; distribute checksummed and attested wheels through GitHub Releases instead.

### Fixed

- Treat positive and negative floating-point zero as the same tie in native Spearman ranking.
