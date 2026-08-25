# Architecture

This page is the shortest complete statement of Lacuna's architecture. It is a contract for implementation work, while the repository-root `LACUNA_TECHNICAL_SPEC.md` remains the complete product vision.

## Status vocabulary

Lacuna documentation uses three status labels:

- **Implemented** — present in the repository and covered by executable checks.
- **v0.1 contract** — the next stable design target; code may not exist yet.
- **Later** — intentionally outside v0.1 and not a reason to generalize today's implementation.

Never describe a target API as implemented. Pre-release code can change, but its current behavior must still be documented accurately.

## Product boundary

Lacuna validates quantitative research. It does not own order routing, exchange simulation, market-data distribution, alpha generation, or live deployment.

```text
research idea
    ↓
signal and explicit labels
    ↓
efficacy and statistical evidence
    ↓
leakage, bias, and robustness checks
    ↓
cost and capacity stress
    ↓
structured audit evidence
```

Existing dataframe libraries, research notebooks, and backtest engines remain outside Lacuna. Their outputs cross an adapter boundary and become validated semantic frames.

## Runtime layers

```text
┌───────────────────────────────────────────────────────────────┐
│ User research: Polars · pandas · NumPy · Arrow · backtesters │
└──────────────────────────────┬────────────────────────────────┘
                               │ supported adapters
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ Typed Python API                                               │
│ input naming · configuration · validation · result assembly   │
└──────────────────────────────┬────────────────────────────────┘
                               │ normalized, coarse-grained calls
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ Arrow-compatible columnar boundary                            │
│ semantic schemas · copy/materialization policy · null policy  │
└───────────────┬──────────────────────┬────────────────────────┘
                │                      │
                ▼                      ▼
┌────────────────────────┐  ┌───────────────────────────────────┐
│ Rust native kernels    │  │ Polars · NumPy · SciPy            │
│ quant-specific hot path│  │ mature columnar/numerical methods │
└───────────────┬────────┘  └──────────────────┬────────────────┘
                └──────────────────────┬────────┘
                                       ▼
┌───────────────────────────────────────────────────────────────┐
│ Immutable structured results                                  │
│ metrics · tables · findings · provenance · method versions    │
└──────────────────────────────┬────────────────────────────────┘
                               ▼
                  JSON · Markdown · optional HTML
```

## Dependency direction

Dependencies point inward toward small, stable contracts:

```text
reporting ───────► structured results
audit rules ─────► domain results + findings
studies ─────────► functional domain APIs
domain APIs ─────► adapters + execution routing
native binding ──► lacuna-core
adapters ────────► third-party edge formats
```

The following directions are forbidden:

- `lacuna-core` depending on Python or presentation concerns;
- numerical kernels constructing Python result objects;
- reporting code recomputing statistics;
- core domain modules importing pandas, DuckDB, plotting, or ML packages unconditionally;
- adapters becoming the location of domain logic;
- audit rules treating missing inputs as successful evidence.

## Execution ownership

Choose an execution path by the nature of the operation, not by prestige:

| Work | Default owner |
|---|---|
| Lazy scans, projection, grouping, joins, windows | Polars |
| Universal array operations and small vectorized routines | NumPy |
| Distributions, linear algebra, established tests | SciPy extra |
| Quant-specific repeated kernels with measured Python overhead | Rust |
| Input naming and semantic validation | Python |
| Formatting, charts, HTML | Reporting extra |

A Rust implementation requires a correct reference path and benchmark evidence. A dataframe expression stays in Polars when moving it to Rust would merely duplicate a mature engine.

## Configuration and state

Configuration is explicit and scoped. The implemented foundation exposes immutable `Config` values through `lacuna.config(...)` and `lacuna.configure(...)`.

Analyses must not depend on hidden module state. Randomized methods receive or derive a recorded seed. Thread budgets, memory limits, cache locations, and algorithm choices belong in configuration or explicit method parameters and must appear in provenance when they affect a result.

## Data and evidence contracts

Lacuna has no proprietary dataframe. It has semantic contracts over ordinary columnar data. See [Data and time](data-model.md) for schemas and temporal invariants.

Every analysis returns structured evidence before presentation. See [Results and evidence](evidence-model.md) for result, finding, provenance, and serialization rules.

## Package ownership

The target Python packages have narrow responsibilities:

| Package | Owns |
|---|---|
| `signal` | IC, quantiles, decay, turnover, neutralization |
| `labels` | forward returns, event intervals, execution timing |
| `cv` | temporal splits, purging, embargo, and CPCV path reconstruction |
| `validation` | resampling, permutation, Sharpe/PBO, Reality Check/SPA, multiple testing, stability |
| `regime` | regime definitions and conditional evidence |
| `costs` | cost models, stress surfaces, impact, capacity |
| `bias` | point-in-time joins, leakage, survivorship, universe checks |
| `audit` | rule applicability, findings, aggregation, scoring policy |
| `report` | Markdown/JSON/HTML rendering from result objects |
| `adapters` | supported edge-format normalization only |
| `experiment` | trials, registries, fingerprints, reproducibility |

Do not create every package as an empty placeholder. Add a package when its first cohesive public capability is implemented.

## Current implementation

The repository currently implements the v0.1 signal-validation path, v0.2 robustness milestone,
v0.3 trading-realism milestone, v0.4 data-correctness milestone, and v0.5 advanced-inference
milestone:

- mixed Python/Rust packaging through maturin and PyO3;
- explicit runtime configuration;
- immutable result, finding, and provenance models;
- Polars-first normalization for Polars, pandas, Arrow-compatible, mapping, and NumPy inputs;
- explicit forward-return labels and Pearson/Spearman IC, quantile, turnover, and decay diagnostics;
- walk-forward folds, half-open interval purging, observation embargo, and four bootstrap schemes;
- native grouped-rank IC, bootstrap-mean, and interval-purge kernels with reference paths;
- deterministic audit rules, evidence scoring, JSON/Markdown/basic HTML, and `SignalStudy`;
- `doctor`, `signal`, and developer `bench` CLI workflows;
- published result schema, golden fixtures, layered tests, and reproducible benchmark suites;
- canonical experiment fingerprints, append-only attempts/corrections, and selection lineage;
- Bonferroni, Holm, Benjamini-Hochberg, and Benjamini-Yekutieli corrections;
- parameter surfaces, seeded perturbations, subperiods, and timestamped universe scenarios;
- trailing/retrospective regime classification and conditional concentration evidence.
- immutable cost-model estimates; commission, spread, slippage, impact, and borrow models;
- deterministic cost stress, bracketed break-even solving, point-in-time liquidity diagnostics,
  and scenario capacity curves.
- safe as-of joins, future-data and revision diagnostics, survivorship evidence, half-open
  membership selection, universe drift, and declarative dataset validation.
- CPCV paths, explicit permutation nulls, Sharpe/PSR/DSR/MinTRL, CSCV/PBO, joint stationary
  bootstrap, White Reality Check, and Hansen SPA.

Vendor/backtester integrations and plugins remain later contracts. Pre-1.0 minor versions can
change through documented migrations; the published `0.1.x` through `0.5.x` contracts govern their
respective release lines.

## Detailed guides

- [Developer handbook](../development/index.md)
- [Subsystem contracts](../subsystems/signal-labels.md)
- [Agent handbook](../agents/index.md)
- [Architecture decisions](../reference/architecture-decisions.md)
- [Glossary](../reference/glossary.md)
