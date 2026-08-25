# Changelog

All notable changes to Lacuna will be documented here. The project intends to follow [Semantic Versioning](https://semver.org/) once its public release process begins.

## Unreleased

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
