# Changelog

All notable changes to Lacuna will be documented here. The project intends to follow [Semantic Versioning](https://semver.org/) once its public release process begins.

## Unreleased

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
