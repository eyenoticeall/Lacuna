# Implementation roadmap

The roadmap is dependency-ordered. A later phase does not justify weakening an earlier contract.

## Phase 0 — foundations

**Implemented foundation:** packaging, typed configuration, result/finding models, Polars-first normalization, native bridge, baseline tests, CI, docs, and wheel build.

Remaining foundation hardening before v0.1 includes richer copy diagnostics, domain schema validators, benchmark harness expansion, and persisted schema fixtures.

## Phase 1 — signal diagnostics

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

1. Rule protocol and applicability model.
2. Versioned finding codes and thresholds.
3. Audit context assembled from domain results.
4. JSON and Markdown renderers.
5. Optional escaped HTML renderer.
6. Versioned scoring policy with explicit missing-evidence penalties.

Exit criteria: absent evidence yields `UNKNOWN`; all rendered values trace to result fields; persisted audit fixture is versioned.

## Phase 4 — robustness and experiments

Parameter surfaces, continuous perturbation, subperiods, regime analysis, universe perturbation, and experiment registry/multiple-testing corrections.

Exit criteria: isolated optima and concentration are quantified; trial history is first-class provenance.

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
