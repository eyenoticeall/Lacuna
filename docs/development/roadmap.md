# Implementation roadmap

The roadmap is dependency-ordered. A later phase does not justify weakening an earlier contract.

## Version progression

Roadmap phases are released as pre-1.0 minor versions because each phase adds public analytical
capabilities. Patch versions are reserved for compatible corrections and hardening within a shipped
phase; release candidates use Cargo/SemVer tags such as `v0.2.0-rc.1` and PEP 440 package versions
such as `0.2.0rc1`.

| Version | Roadmap scope | Release condition |
| --- | --- | --- |
| `0.1.x` | Phases 0–3: foundations, signal diagnostics, validation core, audit/reports | Released |
| `0.2.x` | Phase 4: robustness, regimes, experiment lineage, basic multiple-testing correction | Released |
| `0.3.x` | Phase 5: trading realism, cost stress, liquidity, capacity | Released |
| `0.4.x` | Phase 6: point-in-time data correctness and bias detection | Released |
| `0.5.x` | Phase 7 plus deferred inference: permutation, Sharpe/PSR/DSR, CPCV/PBO, Reality Check/SPA | Released |
| `0.6.x` | Phase 8: separately optional adapters and extensions | Released |
| `0.7.x` | Portable, deterministic, independently verifiable evidence bundles | Released |
| `0.8.x` | Versioned cross-phase standardized audit profiles and evidence composition | Released |
| `0.9.x` | Persisted-artifact migration, integrated performance, diagnostics, and reference hardening | Released |
| `0.10.x` | Group-aware signal transformations, attrition, multi-lag stability, interactive evidence | Released |
| `0.11.x` | Validated decay inference, diagnostic portfolio projection, robust event studies | Released |
| `0.12.x` | Generic factor-panel interoperability and migration guidance | Released |
| `0.13.x` | PyPI-safe distribution identity, Trusted Publishing, and registry-install verification | Released |
| `0.14.x` | Admission-gated Rust migration and performance/memory hardening | Released |
| `1.0.0` | Stable product contract in the technical specification | Every v1 definition item is evidenced, including independent use |

This enumeration is a compatibility plan, not a schedule. A phase may receive multiple release
candidates or patch releases, but Lacuna does not claim the next minor version until that phase's
complete public contract is implemented and verified.

## Phase 0 — foundations

**Implemented foundation:** packaging, typed configuration, result/finding models, Polars-first normalization, native bridge, baseline tests, CI, docs, and wheel build.

The audit-result v1 JSON Schema, persisted JSON/Markdown compatibility fixtures, Python end-to-end
benchmarks, Criterion native-kernel benchmarks, conservative copy/materialization diagnostics, and
domain-specific signal/label/price schema validation are implemented.

## Phase 1 — signal diagnostics

**v0.1 implemented:** explicit forward labels, Pearson/Spearman IC, grouped IC time series,
quantile returns and spread, monotonicity, rank turnover/autocorrelation, multi-horizon decay, and
native grouped rank IC.

Deliver in this order:

1. Forward-return labels with explicit observation/entry/exit timing.
2. Pearson IC reference and grouped time series.
3. Spearman IC with documented ties and native grouped ranking.
4. Quantile assignment, returns, spread, and monotonicity components.
5. Turnover and signal autocorrelation.
6. Multi-horizon decay.
7. Structured Markdown report over the same results.

Exit criteria: Polars, NumPy, and optional pandas inputs agree; methodology is complete; native IC has differential tests and benchmarks.

## Phase 2 — validation

**v0.1 implemented:** expanding/rolling walk-forward folds, interval-aware purging, observation-count
embargo, and deterministic IID/moving/circular/stationary bootstrap confidence intervals.

1. Walk-forward split definitions and visualizable fold table.
2. Interval-aware purging and embargo.
3. IID reference bootstrap.
4. Moving block and stationary bootstrap with deterministic streams.
5. **Later:** permutation schemes.
6. **Later:** Sharpe uncertainty, then PSR and DSR with assumptions.

Exit criteria: no post-purge overlap in property tests; bootstrap calibration simulations pass; seeds reproduce across thread counts.

## Phase 3 — audit and reports

**v0.1 implemented:** immutable audit contexts, independently executable versioned rules, explicit
applicability, a 100-weight score with visible evidence coverage, deterministic JSON/Markdown/basic
HTML, the `SignalStudy` facade, and the `lacuna signal` file workflow.

1. Rule protocol and applicability model.
2. Versioned finding codes and thresholds.
3. Audit context assembled from domain results.
4. JSON and Markdown renderers.
5. Optional escaped HTML renderer.
6. Versioned scoring policy with explicit missing-evidence penalties.

Exit criteria: absent evidence yields `UNKNOWN`; all rendered values trace to result fields; persisted audit fixture is versioned.

## Phase 4 — robustness and experiments

**v0.2 implemented:** parameter surfaces, continuous perturbation, subperiods, regime analysis,
universe perturbation, append-only experiment lineage, selection records, canonical fingerprints,
and multiple-testing corrections.

Deliver for `0.2.0` in this order:

1. Canonical parameter encoding, fingerprints, immutable attempt records, and append-only local
   registry storage.
2. Explicit selection lineage over the complete eligible candidate set.
3. Parameter surfaces with visible failed points, mixed-type adjacency, boundary detection, and
   isolated-optimum evidence.
4. Deterministic continuous perturbation with rejection accounting.
5. Declared subperiod and universe perturbation tables with retained-sample/composition evidence.
6. Point-in-time or explicitly retrospective regime classification and conditional evidence.
7. Bonferroni, Holm, Benjamini-Hochberg, and Benjamini-Yekutieli adjustments over registered trial
   families.

Exit criteria: isolated optima and concentration are quantified; trial history is first-class provenance.

The exit criteria are covered by planted isolated/plateau and regime-concentration fixtures,
deterministic perturbation tests, point-in-time threshold tests, append-only/concurrent registry
tests, and the frozen `0.2.x` public API contract.

## Phase 5 — trading realism

**v0.3 implemented:** an immutable cost-model protocol and estimates; commission, observed/assumed
spread, fixed/proportional/volatility-scaled slippage, participation/square-root impact, and borrow;
deterministic grid/correlated stress scenarios; monotonic bracketed break-even solving; point-in-time
or retrospective liquidity evidence; and multi-scenario capacity curves.

Exit criteria: cost monotonicity properties pass; outputs show assumptions and uncertainty rather than one false-precision capacity number.

The exit criteria are covered by hand-computed component fixtures, monotonicity/symmetry/
reconciliation properties, double-application guards, future-market-data tests, planted
break-even/impact/capacity cases, explicit unknown liquidity and borrow evidence, Polars/pandas/Arrow
equivalence, a frozen `0.3.x` public contract, and a versioned end-to-end stress benchmark. The
benchmark supports the NumPy/Polars path; no unevidenced native cost path is shipped.

## Phase 6 — data correctness

**v0.4 implemented:** point-in-time as-of joins with deterministic revision ties, explicit
availability/revision semantics, direct future-data checks and optional materiality, structural
revision diagnostics, three-state survivorship evidence, half-open membership selection with an
availability firewall, consecutive universe drift, and declarative dataset validation.

Exit criteria: safe joins never select unavailable records; unknown survivorship handling remains visible.

The exit criteria are covered by exact-boundary, one-nanosecond-future, timezone, staleness,
revision, delisted-asset, overlap, future-known-membership, drift, and dataset-defect fixtures;
generated join/membership invariants; Polars/pandas/Arrow equivalence; a frozen `0.4.x` public
contract; an end-to-end as-of benchmark; and clean-wheel exercise of the bias path.

## Phase 7 — advanced inference

**v0.5 implemented:** combinatorial purged K-fold with inspectable reconstructed paths; explicit
permutation nulls; Sharpe uncertainty, PSR, DSR, and minimum track-record length; symmetric
CSCV/PBO with visible selection/ranks/logits and partition sensitivity; joint stationary bootstrap;
White Reality Check; and Hansen SPA with lower, consistent, and upper recenterings.

Exit criteria: every method has an independent equation-level reference or deterministic stream
fixture, a fixed-seed simulation for its statistical behavior, explicit assumptions and failure
states, bounded combinatorial work, a frozen additive `0.5.x` API, clean-wheel exercise, and a
versioned public-call benchmark.

The exit criteria are covered by CPCV combination/path and no-overlap invariants; permutation and
Sharpe null simulations; complete-family DSR checks; planted PBO stable-edge/forced-overfit cases;
independent literal White and Hansen implementations; Reality Check/SPA size, power, and
poor-alternative simulations; benchmark artifact v4; and the advanced-inference methodology
contract. No native advanced-inference path is claimed without a future benchmark-justified,
differentially tested implementation.

## Phase 8 — extensions

**v0.6 implemented:** optional integrations are explicit boundaries rather than new
research methodology. Core adds no mandatory runtime dependency.

Delivered in dependency order:

1. Immutable `AdaptedFrame` evidence and collision-safe canonical/source normalization.
2. DuckDB result-to-Arrow-stream ingestion without pandas or SQL construction.
3. A dependency-free scikit-learn CV protocol bridge over frozen Lacuna temporal folds.
4. Versioned vendor mappings with availability, revision, timezone, adjustment, and identity
   declarations.
5. Generic returns/trades/positions mappings that require complete backtest timing, gross/net,
   compounding, costs, borrow, calendar, session, missing-asset, and delisting semantics.
6. Domain-specific entry-point groups with metadata-only discovery, deterministic conflict handling,
   explicit trusted activation, and protocol/capability negotiation.
7. A separate `lacuna-options` 0.1 distribution with validated empirical chains, carry forwards,
   log-forward moneyness, absolute-delta buckets, and supplied-expectation IV residuals.

Exit criteria: optional packages do not load at core import time; real DuckDB and scikit-learn paths
interoperate; discovery never imports targets; activation is explicit and evidenced; adapters reject
ambiguous temporal/methodological semantics; core `0.6.x` and extension `0.1.x` public contracts are
frozen independently; both distributions build, clean-install together, and enter the checksummed,
attested release set.

The release criteria are covered by real DuckDB and scikit-learn interoperability, adapter/plugin
unit and contract fixtures, extension property/adversarial tests, independent frozen API contracts,
clean joint wheel installation, the complete cross-platform CI matrix, and the tagged checksum and
provenance workflow.

Deferred beyond the phase: DataFusion/query pushdown, framework-specific vectorbt/LEAN/Nautilus
helpers, plugin isolation or marketplace behavior, universal IV/Greeks solvers, SVI calibration,
arbitrage repair, and delta-hedged options attribution. They require their own semantic and numerical
contracts and are not implied by the generic boundaries.

## Integration and v1 hardening (`0.7`–`0.9`)

After Phase 8, work is driven by cross-phase use rather than unchecked feature count:

- run complete signal-to-audit workflows over vendor/backtester inputs and extension evidence;
- reconcile configuration, provenance, and error behavior across every public subsystem;
- profile realistic end-to-end workloads and optimize only evidenced bottlenecks;
- test migrations and persisted evidence across release lines;
- collect independent-user feedback and harden installation, diagnostics, and documentation;
- close every remaining v1 definition item in the technical specification or explicitly remove it
  from the stable contract.

`0.7`–`0.9` do not promise one feature per minor version. A release needs a coherent compatibility
milestone, migration story, and complete evidence gate.

The first coherent integration milestone is `0.7`: deterministic `.lacuna` archives over immutable
reports, configuration/environment summaries, and optional structured evidence. Bundle v1 has a
published schema, byte-stable writer, strict non-executing verifier, SHA-256 manifest, privacy
redaction/fail-closed behavior, CLI support, hostile-archive tests, frozen additive API, and
clean-wheel exercise. It claims identifiable reproducibility only; recomputability and numerical or
bitwise reproduction across independent executions are not implied.

The second coherent integration milestone is `0.8`: standardized signal, strategy, and options
profiles over every released evidence method family. The profile schema and API are frozen;
required, optional, and not-applicable coverage is explicit by category; domain findings are
propagated without reinterpretation; no universal score is emitted; strict v1 result JSON and CLI
composition are bounded; vendor, backtester, options, bundle, installed-wheel, and release archive
paths are executable.

The third coherent integration milestone is `0.9`: an explicit identity-migration matrix and
tagged-fixture corpus for persisted formats; strict profile/manifest readers; versioned, non-invasive
installation diagnostics; benchmark artifact v5 with a profiled integrated strategy workflow; and
an exact machine-checked reference route for every supported export. No speculative performance
path was added when profiling found no justified semantic-preserving change.

The current status of every stable-release criterion and the remaining external `1.0` boundary live
in the [v1 readiness ledger](v1-readiness.md).

## Factor-research ergonomics (`0.10`–`0.12`)

These milestones adopt proven factor-research ergonomics without turning Lacuna into a notebook
plotting package, cumulative backtester, or order simulator.

`0.10` introduces immutable `BucketSpec`/`SignalTransformResult` contracts, explicit bucket-return
analysis, availability-aware grouping, weighted least-squares neutralization, reconciled attrition,
exact multi-lag turnover, retained study evidence, and an opt-in Plotly renderer over stored rows.
Core rendering and schema-v1 audit JSON remain unchanged.

`0.11` adds a validated positive exponential decay fit with dependence-aware joint resampling,
explicit diagnostic portfolio weights without compounding or execution simulation, and event
windows anchored to availability with clustered path inference. The portfolio boundary requires an
ADR before implementation.

`0.12` adds generic factor-panel schemas and fully declared timing semantics across Polars, Arrow,
and optional pandas MultiIndexes. It publishes migration guidance and frozen compatible numeric
fixtures pinned to a reviewed upstream commit without a runtime Alphalens dependency.

Excluded throughout: lookahead z-score filtering, implicit calendars or timing, mandatory pandas
or plotting, cumulative backtesting, order/fill simulation, and plotting side effects.

## Admission-gated performance (`0.14`)

`0.14` preserves the complete `0.13` public API, schema-v1 result envelope, analytical method
versions, c14n-v1 identities, and deterministic RNG streams. It profiles every registered
migration candidate against an already optimized NumPy or Polars reference and ships native code
only after correctness plus an end-to-end throughput, memory, or bounded-completion gate.

The implementation and candidate-admission phases are complete. Most candidates finish as
`OPTIMIZED_NON_NATIVE`; shared resampling is `NOT_MIGRATING`, and deferred identity/public-carrier
work is `BLOCKED`. Grouped-rank IC and PBO/CSCV are `SHIPPED_NATIVE` after pinned Linux evidence,
the same `cp311-abi3` wheel on Python 3.11–3.14, and every target-wheel smoke job reproduced their
contracts. The exact-SHA non-publishing preflight remains a tag gate, and the tag workflow refuses
any non-terminal decision.

Native work stays single-threaded. Python retains timing semantics, methodology, validation,
findings, provenance, RNG, and public result construction. Arrow C Data, native RNG/scheduling,
Rayon, public compact carriers, c14n-v2, approximate quantiles, and semantic method changes remain
outside this milestone.

`0.14.1` is a correctness patch within the line. It corrects `SignalStudy.audit` IC inference, which
pooled horizons and resampled overlapping labels as independent, rejects zero-length `next_close`
labels, counts only defined horizons for decay coverage, and honors the robustness failure policy
for constraint errors. The four affected audit rules are at rule version 2; see
[Audit scoring](../methodology/audit-scoring.md#signal-study-assembly).

## Open follow-ups from the 0.14.1 review

A documentation-driven review of 0.14.1 in November 2026 produced the corrections listed under
**Unreleased** in the changelog. The items below were found in the same review and deliberately
left open. Each is its own change: none is a quick patch, and several alter scoring, persisted
identities, or methodology. They are recorded here so they are not rediscovered from scratch.

Two methodology questions from that review are settled and are not open: headline metrics describe
one horizon and never pool horizons, and every balanced quantile assignment uses the midpoint rule.

### Audit and evidence

| Status | Item | Why it was deferred | Starting point |
| --- | --- | --- | --- |
| Open | The standard audit profile recognises no `events.*` method, so `event_windows` and `event_response` results come back as `UNRECOGNIZED_EVIDENCE` (`WARN`). | Method-family membership is versioned. It needs a new capability, not a pattern added to `signal_diagnostics`, plus profile version 2, its fixture, and the schema. | `_BASE_REQUIREMENTS` in `python/lacuna/audit_profiles.py`; `tests/fixtures/standard-audit-profile-v1.json`. |
| Open | `PRICE_ADJUSTMENT_DECLARED` passes for `"raw"`, and `DELISTING_HANDLING_DECLARED` passes once a column is named even if it is entirely null. About 20 of the 100 signal-audit points come from declarations, not measurements. | These are documented as declaration rules. Changing what earns credit is a scoring redesign and needs a new score version. | `_PriceAdjustmentRule` and `_DelistingRule` in `python/lacuna/audit.py`; `docs/methodology/audit-scoring.md`. |
| Open | `PURGED_VALIDATION_SUPPLIED` cannot verify that a split was built from the audited labels. It passes with `data_identity_verified: false`, and its zero-purge warning also fires for legitimately sampled, non-overlapping labels. | Split evidence carries no input fingerprint. Adding one changes `cv.*` evidence and needs a matching fingerprint on label evidence to compare against. | `_split_evidence` in `python/lacuna/cv.py`; `_PurgedValidationRule` in `python/lacuna/audit.py`. |
| Open | `lc.audit()` and `standard_audit()` keep no evidence, so the Plotly view and bundles need `evidence=` passed explicitly, unlike `SignalStudy.audit`. | An API behavior change on a frozen public surface; needs a decision on retention and memory cost. | `python/lacuna/audit.py`, `python/lacuna/report.py`. |
| Open | A bare multi-horizon label frame has a null headline because it declares no horizon order, and there is no way to declare one. | A `headline_horizon=` parameter changes frozen public signatures, so it belongs to the next API revision. | `_headline_horizon` in `python/lacuna/signal.py`. |

### Point-in-time and bias

| Status | Item | Why it was deferred | Starting point |
| --- | --- | --- | --- |
| Open | `asof_join(effective_time=...)` is validated and recorded but does not affect matching, so a late restatement of an older period outranks a newer period's first print. | The specification defines no matching role for it. Ordering by effective time is a methodology decision, not a fix. | `docs/subsystems/bias-point-in-time.md` ("Implemented parameter semantics"). |
| Open | `revision_diagnostics` still accepts string and categorical revisions, which sort lexicographically (`"10"` below `"9"`). `asof_join` now rejects them. | Out of scope of the as-of fix; rejecting them changes an explicitly allowed input. | `revision_diagnostics` in `python/lacuna/bias.py`; reuse `_require_orderable_revision`. |
| Open | `asof_join` on a `Duration` time column fails inside `_portable_records` with a Polars cast error. | Separate from the tolerance validation that surfaced it. | `_portable_records` in `python/lacuna/bias.py`. |

### Validation, events, and regimes

| Status | Item | Why it was deferred | Starting point |
| --- | --- | --- | --- |
| Open | `event_response` resamples ordered anchor-time clusters only. Same-instrument `overlap_cluster` groups are reported but are not a resampling unit, and the result still passes when overlap exists (the overlap warning travels with it). | Resampling overlap clusters as units is a methodology change and needs a null-calibration study first. | `docs/subsystems/event-studies.md`; `event_response` in `python/lacuna/events.py`. |
| Open | `regime_analysis` cannot cross-check `classification_mode` against how labels were built, because it accepts only a table. | Needs a new input path that accepts a `quantile_regimes` result and its provenance. | `python/lacuna/regime.py`. |
| Open | `WalkForward` in calendar mode over midnight-stamped daily `Datetime` bars still drops the final window; only `Date` columns get whole-day coverage. | A `Datetime` has no declared bar length, and inferring cadence would be a silent methodology choice. A declared bar-length parameter would resolve it. | `WalkForward.split` in `python/lacuna/cv.py`. |
| Open | `SklearnCV` checks only that `X` and `y` have the split's row count, not that they are in the same row order. | No identity travels with `X`; documented in the docstring instead. | `python/lacuna/adapters/sklearn.py`. |

### Costs

| Status | Item | Why it was deferred | Starting point |
| --- | --- | --- | --- |
| Open | Net Sharpe and CAGR in `stress`, `break_even_cost`, and `capacity_curve` use only periods that contain a trade; results warn about it. | Counting trade-free periods needs a declared period calendar, which is a new parameter and a method version. | `_period_aggregate_matrix` in `python/lacuna/costs.py`. |
| Open | `BorrowCostModel` is stateless and charges every negative-quantity row over its declared `holding_days`. | Position-aware borrow accrual needs ordering, opening positions, and its own contract. | `BorrowCostModel` in `python/lacuna/costs.py`. |

### Reproducibility and persistence

| Status | Item | Why it was deferred | Starting point |
| --- | --- | --- | --- |
| Open | `ExperimentRegistry` is append-only through the API only. The SQLite schema has no triggers, so `UPDATE` and `DELETE` through `sqlite3` succeed silently. | Triggers change the stored schema; existing databases need a migration path and the superseding-record flow must keep working. | `_initialize` in `python/lacuna/experiment.py`. |
| Open | `schemas/persisted-artifact-compatibility-v1.json` still declares consumer package series `0.9`, and its producer lists stop at `0.9`. A regression test pins that value. | It is a release-time artifact; refresh it with the next release rather than mid-line. | `tests/regression/test_persisted_artifact_compatibility.py`. |
| Open | Packaged schema `$id` values use `lacuna.dev`, while the project site is `lacuna.run`. | A `$id` is a persisted identity. Changing it needs a decision on whether old identifiers stay resolvable. | `schemas/*.schema.json`. |
| Open | Bundle digests differ across CLI runs because `created_at` is stamped per run, and nothing pins it. | Needs a decision between a `SOURCE_DATE_EPOCH`-style input and excluding the timestamp from the digest. | `python/lacuna/bundle.py`, `python/lacuna/cli.py`. |
| Open | `lacuna-options` evidence carries no `input_fingerprint`. | The core fingerprint helpers that handle timezones portably are private; the extension needs a public one, and a decision on what the fingerprint covers. | `extensions/lacuna-options/CHANGELOG.md` ("Deferred"); `_frames.frame_records`. |
| Open | `NativeExtensionError` is exported but never raised. | Removing an export breaks the frozen API; raising it needs a capability that has no fallback. | `python/lacuna/exceptions.py`. |

### Before the release that ships the Unreleased corrections

- Run the gates that were not run on the development machine: `cargo clippy`, `cargo test`,
  `uv build`, and the pandas, pyarrow, DuckDB, and scikit-learn paths.
- Expect the same-runner benchmark guard to fail once on the ten changed checksums recorded in the
  [performance guide](performance.md). The recorded timings were taken on a loaded machine; replace
  them with the CI job's same-runner numbers.
- The website documentation describes released behavior. It needs an update pass when the release
  ships, including the turnover bucket rule and the multi-horizon headline definition.

## Historical v0.1 boundary

v0.1 turns a cross-sectional signal into a rigorous diagnostics report. It excludes live trading, full backtesting, distributed execution, GPU kernels, advanced impact simulation, and a plugin marketplace.

The release is ready when the narrow path is correct, reproducible, benchmarked, documented, and usable across supported dataframe inputs—not when every long-term module exists.
