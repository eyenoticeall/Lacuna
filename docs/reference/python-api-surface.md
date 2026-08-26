# Python API surface

This is the complete import inventory for Lacuna core `0.9.x`. It answers where a supported name
lives and routes each module to the document that defines its semantics. Callable signatures are
frozen by the cumulative `tests/fixtures/public-api-v0.*.json` contracts; formulas, temporal rules,
failure modes, and result interpretation live in the linked design and methodology pages.

The adjacent
[public-reference coverage manifest](public-reference-coverage-v1.json) is the machine-readable
source for this inventory. Contract tests require it to match the running package, the cumulative
version fixtures, this page, and every routed document. An export cannot be added with no reference
route, and documentation cannot silently describe a removed export.

Prefer the package root for ordinary work:

```python
import lacuna as lc

result = lc.signal.ic(signal_data, label_data)
report = lc.standard_audit(results={"ic": result}, scope="signal")
```

Submodule imports are supported only for the modules enumerated below. Names from internal modules,
including modules beginning with `_`, are not public merely because Python can import them.

## Common contracts

- Analytical calls return immutable `AnalysisResult` evidence or a typed container carrying one.
- `schema_version` governs serialization, `method_version` governs analytical meaning, and package
  versions govern import compatibility. They are intentionally independent.
- Missing or unverifiable research evidence stays explicit; it is not converted to a passing state.
- Invalid method choices raise `MethodContractError`; invalid data raises `DataContractError`;
  operational subclasses remain under `LacunaError`.
- Public services validate Python-side semantics before any native dispatch. `lacuna._native` is not
  a supported direct API.
- Plugin discovery is metadata-only. Third-party code runs only through explicit activation.

## `lacuna`

The root is the ergonomic workflow surface. Configuration, result/report types, exceptions,
standardized audit, bundles, diagnostics, benchmarks, and the primary analytical namespaces are
available without importing implementation modules. See [Python API design](../development/python-api.md).

Exports: `BUNDLE_FORMAT`, `BUNDLE_VERSION`, `DIAGNOSTIC_VERSION`, `AnalysisResult`, `Applicability`,
`ApplicabilityState`, `AuditContext`, `AuditProfile`, `AuditReport`, `AuditRule`, `AuditScope`,
`BenchmarkCase`, `BenchmarkConfig`, `BenchmarkSuite`, `BundleArtifact`, `BundleManifest`,
`BundleVerification`, `Config`, `ConfigurationError`, `DataContractError`, `DiagnosticCheck`,
`DiagnosticState`, `EvidenceDisposition`, `EvidenceRequirement`, `ExperimentRegistry`, `Finding`,
`FindingState`, `InstallationDiagnostics`, `LabelResult`, `LacunaError`, `MethodContractError`,
`NativeExtensionError`, `PluginError`, `ReportError`, `ResultMetadata`, `Severity`, `SignalStudy`,
`__version__`, `adapters`, `audit`, `benchmark_config_for_tier`, `bias`, `bundle`, `config`,
`configure`, `costs`, `create_bundle`, `cv`, `default_rules`, `diagnose_installation`, `diagnostics`,
`experiment`, `get_config`, `labels`, `plugins`, `regime`, `robustness`, `run_audit`,
`run_benchmarks`, `run_standard_audit`, `signal`, `standard_audit`, `standard_profile`, `validation`,
`verify_bundle`.

## `lacuna.adapters`

Normalizes physical inputs and external artifacts while retaining copy, availability, schema, and
methodology declarations. DuckDB reads through Arrow; sklearn receives frozen temporal splits; vendor
and backtest schemas do not certify caller declarations. See
[Adapters, execution, and plugins](../subsystems/adapters-execution-plugins.md).

Exports: `AdaptedFrame`, `AvailabilityPolicy`, `BacktestArtifactKind`, `BacktestSchema`,
`BacktestSemantics`, `FrameSummary`, `PolarsFrame`, `RevisionPolicy`, `SklearnCV`, `SupportedSplitter`,
`VendorSchema`, `adapt_backtest`, `adapt_vendor`, `as_sklearn_cv`, `frame_summary`, `from_duckdb`,
`require_columns`, `to_polars`.

## `lacuna.audit`

Runs the frozen signal-audit rule engine. Rule applicability is separate from finding state, and
policy declarations never substitute for missing evidence. See
[Audit and reporting](../subsystems/audit-reporting.md).

Exports: `Applicability`, `ApplicabilityState`, `AuditContext`, `AuditRule`, `audit`, `default_rules`,
`run_audit`.

## `lacuna.audit_profiles`

Defines versioned signal, strategy, and options evidence inventories and composes recognized source
results without inventing a cross-domain score. See
[Standardized audit](standardized-audit.md).

Exports: `AuditProfile`, `AuditScope`, `EvidenceDisposition`, `EvidenceRequirement`,
`run_standard_audit`, `standard_audit`, `standard_profile`.

## `lacuna.benchmark`

Produces environment-labelled, checksum-protected timing and traced-memory evidence. Timings are
measurements, not portable latency promises. See [Performance](../development/performance.md).

Exports: `BenchmarkCase`, `BenchmarkConfig`, `BenchmarkSuite`, `benchmark_config_for_tier`,
`run_benchmarks`.

## `lacuna.bias`

Implements availability-safe joins, future/revision checks, survivorship states, half-open historical
membership, universe drift, and dataset declarations. See
[Bias and point-in-time safety](../subsystems/bias-point-in-time.md).

Exports: `AsOfTolerance`, `DatasetSpec`, `MembershipResult`, `PointInTimeJoinResult`, `RevisionMode`,
`SurvivorshipStatus`, `UnmatchedPolicy`, `asof_join`, `future_data_check`, `membership_at`,
`revision_diagnostics`, `survivorship_diagnostics`, `universe_drift`, `validate_dataset`.

## `lacuna.bundle`

Creates deterministic `.lacuna` archives and performs bounded, non-executing structure and digest
verification. Integrity does not imply publisher authenticity. See
[Reproducibility bundle](reproducibility-bundle.md).

Exports: `BUNDLE_FORMAT`, `BUNDLE_VERSION`, `BundleArtifact`, `BundleManifest`, `BundleVerification`,
`create_bundle`, `verify_bundle`.

## `lacuna.costs`

Models explicit commission, spread, slippage, impact, borrow, stress, break-even, liquidity, and
capacity assumptions. Units and quantity conventions are never inferred silently. See
[Costs and capacity](../subsystems/costs-capacity.md).

Exports: `BorrowCostModel`, `BreakEvenMetric`, `CapacityScenario`, `CommissionModel`,
`CompositeCostModel`, `CostEstimate`, `CostModel`, `CostScenario`, `CostUnit`, `LiquidityMode`,
`MissingBorrowPolicy`, `ParticipationImpactModel`, `QuantityConvention`, `SlippageModel`, `SpreadMode`,
`SpreadModel`, `SquareRootImpactModel`, `TradeColumns`, `VolatilitySlippageModel`, `break_even_cost`,
`capacity_curve`, `liquidity_diagnostics`, `stress`.

## `lacuna.cv`

Builds walk-forward, purged, embargoed, and combinatorial temporal splits with visible row identities
and complete path evidence. See [Financial validation](../subsystems/financial-validation.md).

Exports: `CPCVPath`, `CombinatorialPurgedKFold`, `CombinatorialSplitResult`, `Duration`, `Fold`,
`PurgedKFold`, `SplitResult`, `WalkForward`.

## `lacuna.diagnostics`

Inspects package/native identity, supported runtime, dependencies, packaged contracts, and
configuration without reading research data or activating plugins. See
[Installation diagnostics](../development/installation-diagnostics.md).

Exports: `DIAGNOSTIC_VERSION`, `DiagnosticCheck`, `DiagnosticState`, `InstallationDiagnostics`,
`diagnose_installation`.

## `lacuna.experiment`

Provides deterministic canonical identities and append-only experiment, correction, and selection
lineage. Credential-shaped fields are rejected from canonical records. See
[Experiments and reproducibility](../subsystems/experiments-reproducibility.md).

Exports: `CANONICALIZATION_VERSION`, `REGISTRY_SCHEMA_VERSION`, `AttemptRecord`, `AttemptStatus`,
`ExperimentRegistry`, `SelectionRecord`, `canonical_json`, `fingerprint`.

## `lacuna.labels`

Constructs explicit forward-return labels with observation-count horizons, entry timing, adjustment,
delisting, and missing-price semantics. See [Signals and labels](../subsystems/signal-labels.md).

Exports: `Horizon`, `LabelResult`, `PriceAdjustment`, `forward_returns`.

## `lacuna.plugins`

Discovers entry-point metadata, resolves deterministic candidates, negotiates protocol/capabilities,
and activates only the explicitly selected trusted package. See
[Adapters, execution, and plugins](../subsystems/adapters-execution-plugins.md).

Exports: `ENTRY_POINT_GROUPS`, `ActivatedPlugin`, `PluginCandidate`, `PluginDescriptor`, `PluginGroup`,
`activate_plugin`, `discover_plugins`, `select_plugin`.

## `lacuna.regime`

Classifies fixed, trailing, or explicitly retrospective regimes and evaluates conditional evidence
without presenting hindsight as point-in-time knowledge. See
[Robustness](../subsystems/robustness.md).

Exports: `ClassificationMode`, `QuantileMethod`, `quantile_regimes`, `regime_analysis`.

## `lacuna.report`

Projects immutable audit evidence into canonical JSON, Markdown, and self-contained escaped HTML.
Rendering does not reinterpret finding states. See [Audit and reporting](../subsystems/audit-reporting.md).

Exports: `AuditReport`, `render_html`, `render_markdown`.

## `lacuna.robustness`

Evaluates declared parameter, continuous, subperiod, and timestamped-universe perturbations with
explicit failure policy and objective direction. See [Robustness](../subsystems/robustness.md).

Exports: `Distribution`, `FailurePolicy`, `ObjectiveDirection`, `PerturbationSpec`, `Subperiod`,
`UniverseScenario`, `continuous_perturbation`, `subperiod_analysis`, `universe_perturbation`.

## `lacuna.schemas`

Loads the packaged result, bundle, standardized-profile, and persisted-compatibility machine
contracts as text. Loading a schema never executes persisted content. See
[Persisted artifacts](persisted-artifacts.md).

Exports: `audit_result_v1_text`, `bundle_manifest_v1_text`,
`persisted_artifact_compatibility_v1_text`, `standard_audit_profile_v1_text`.

## `lacuna.signal`

Computes Pearson/Spearman information coefficient, balanced quantile evidence, turnover, and
multi-horizon decay over explicit label contracts. See [Signals and labels](../subsystems/signal-labels.md).

Exports: `CorrelationMethod`, `decay`, `ic`, `quantiles`, `turnover`.

## `lacuna.validation`

Provides dependent bootstrap, permutation, Sharpe/PSR/DSR, CPCV-adjacent selection-aware inference,
PBO, joint bootstrap, Reality Check, SPA, multiple testing, and parameter surfaces. See
[Financial validation](../subsystems/financial-validation.md).

Exports: `BootstrapMethod`, `IntervalMethod`, `MultipleTestingMethod`, `ObjectiveDirection`,
`PBOStatistic`, `PBOTieBreak`, `PermutationAlternative`, `PermutationScheme`, `PermutationStatistic`,
`Statistic`, `SurfaceFailurePolicy`, `bootstrap`, `joint_stationary_bootstrap`, `multiple_testing`,
`parameter_surface`, `permutation_test`, `probability_of_backtest_overfitting`, `reality_check`,
`sharpe_inference`, `superior_predictive_ability`.

## Updating the inventory

Treat the manifest, this page, API fixture, implementation, design route, and changelog as one
change. Additive exports belong in the current series fixture; removals or signature changes need an
explicit compatibility decision and migration guidance. Run
`tests/contract/test_public_reference_coverage.py` before release packaging.
