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
| `0.3.x` | Phase 5: trading realism, cost stress, liquidity, capacity | Complete Phase 5 contracts and exit criteria |
| `0.4.x` | Phase 6: point-in-time data correctness and bias detection | Complete Phase 6 contracts and exit criteria |
| `0.5.x` | Phase 7 plus deferred inference: permutation, Sharpe/PSR/DSR, CPCV/PBO, Reality Check/SPA | Validated reference and simulation suites for every method |
| `0.6.x` | Phase 8: separately optional adapters and extensions | Core dependency surface remains unchanged |
| `0.7`–`0.9` | Cross-phase integration, migration, performance, and real-user hardening | No missing v1 contract or unresolved release blocker |
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

Cost-model protocol, commission/spread/slippage models, stress surfaces, break-even costs, impact scenarios, and capacity curves.

Exit criteria: cost monotonicity properties pass; outputs show assumptions and uncertainty rather than one false-precision capacity number.

## Phase 6 — data correctness

Point-in-time as-of joins, availability/revision semantics, future-data checks, survivorship status, universe drift, and index membership intervals.

Exit criteria: safe joins never select unavailable records; unknown survivorship handling remains visible.

## Phase 7 — advanced inference

CPCV/PBO, advanced dependent resampling, White Reality Check, and Hansen SPA only after validated reference implementations and simulation suites exist.

## Phase 8 — extensions

Options research, ML adapters, vendor schemas, and framework adapters remain separate extensions. They do not expand core dependencies or turn Lacuna into a backtester.

## v0.1 boundary

v0.1 turns a cross-sectional signal into a rigorous diagnostics report. It excludes live trading, full backtesting, distributed execution, GPU kernels, advanced impact simulation, and a plugin marketplace.

The release is ready when the narrow path is correct, reproducible, benchmarked, documented, and usable across supported dataframe inputs—not when every long-term module exists.
