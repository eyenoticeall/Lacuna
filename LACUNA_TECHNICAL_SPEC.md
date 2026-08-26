# Lacuna

> **Open-source quantitative research validation for finding where alpha breaks.**
>
> **Working tagline:** *Stress-test your alpha before the market does.*

**Document type:** Technical specification / architecture proposal  
**Status:** Draft design specification  
**Date:** 2026-08-25  
**Primary language:** Python  
**Performance core:** Rust  
**Primary data model:** Apache Arrow-compatible columnar data  
**License:** MIT

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [What Lacuna Is](#2-what-lacuna-is)
3. [What Lacuna Is Not](#3-what-lacuna-is-not)
4. [Design Goals](#4-design-goals)
5. [Core Design Principles](#5-core-design-principles)
6. [High-Level Architecture](#6-high-level-architecture)
7. [Recommended Technology Stack](#7-recommended-technology-stack)
8. [Performance Architecture](#8-performance-architecture)
9. [Canonical Data Model](#9-canonical-data-model)
10. [Core Package Structure](#10-core-package-structure)
11. [Signal Research](#11-signal-research)
12. [Forward Returns and Labels](#12-forward-returns-and-labels)
13. [Financial Cross-Validation](#13-financial-cross-validation)
14. [Statistical Validation](#14-statistical-validation)
15. [Multiple-Testing and Backtest-Overfitting Controls](#15-multiple-testing-and-backtest-overfitting-controls)
16. [Parameter Stability](#16-parameter-stability)
17. [Regime Analysis](#17-regime-analysis)
18. [Transaction-Cost and Capacity Analysis](#18-transaction-cost-and-capacity-analysis)
19. [Point-in-Time Correctness and Bias Detection](#19-point-in-time-correctness-and-bias-detection)
20. [The Audit Engine](#20-the-audit-engine)
21. [Reporting](#21-reporting)
22. [Adapters and Interoperability](#22-adapters-and-interoperability)
23. [Caching, Provenance, and Reproducibility](#23-caching-provenance-and-reproducibility)
24. [Parallelism and Execution](#24-parallelism-and-execution)
25. [Numerical Correctness](#25-numerical-correctness)
26. [Plugin Architecture](#26-plugin-architecture)
27. [Optional Options-Research Extension](#27-optional-options-research-extension)
28. [Python API Design](#28-python-api-design)
29. [CLI Design](#29-cli-design)
30. [Repository Layout](#30-repository-layout)
31. [Testing Strategy](#31-testing-strategy)
32. [Benchmarking and Performance Regression](#32-benchmarking-and-performance-regression)
33. [Packaging and Distribution](#33-packaging-and-distribution)
34. [Documentation](#34-documentation)
35. [Security and Trust Boundaries](#35-security-and-trust-boundaries)
36. [Licensing and Governance](#36-licensing-and-governance)
37. [Roadmap](#37-roadmap)
38. [v0.1 Scope](#38-v01-scope)
39. [v1.0 Definition](#39-v10-definition)
40. [Example End-to-End Workflow](#40-example-end-to-end-workflow)
41. [Key Architectural Decisions](#41-key-architectural-decisions)
42. [Success Criteria](#42-success-criteria)
43. [Technology Reference Notes](#43-technology-reference-notes)

---

# 1. Executive Summary

**Lacuna** is an open-source quantitative research library designed to answer a question that most backtesting frameworks do not answer well:

> **Is there credible evidence that this signal or strategy contains durable information, or have we fooled ourselves?**

The quant ecosystem already has capable tools for:

- manipulating data;
- pricing derivatives;
- running backtests;
- simulating execution;
- optimizing portfolios;
- calculating performance statistics;
- deploying live strategies.

The comparatively weak and fragmented layer is the one between **research idea** and **backtest confidence**.

Lacuna fills that gap.

It should provide a rigorous, fast, engine-agnostic toolkit for:

- cross-sectional signal analysis;
- forward-return analysis;
- factor decay;
- information coefficients;
- quantile spreads;
- turnover;
- financial cross-validation;
- purging and embargo;
- bootstrap and permutation inference;
- Probabilistic Sharpe Ratio;
- Deflated Sharpe Ratio;
- multiple-hypothesis corrections;
- probability-of-backtest-overfitting analysis;
- parameter perturbation;
- universe perturbation;
- temporal stability;
- regime decomposition;
- cost and capacity stress testing;
- point-in-time correctness checks;
- survivorship-bias warnings;
- leakage detection;
- reproducible research provenance;
- standardized audit reports.

The intended identity is not:

> another algorithmic-trading framework.

It is:

> **the validation and diagnostics layer that can sit on top of almost any quantitative workflow.**

A user should be able to research in Polars, pandas, NumPy, vectorbt, LEAN, NautilusTrader, Zipline, a proprietary system, or a notebook and still use Lacuna.

The ideal experience is:

```python
import lacuna as lc

study = lc.SignalStudy(
    signal=signal,
    prices=prices,
    horizons=["1D", "5D", "20D"],
)

report = study.audit()
report.show()
```

or:

```python
audit = lc.audit(
    returns=strategy_returns,
    trades=trades,
    trials=experiment_history,
)

audit.to_html("lacuna-audit.html")
```

The implementation should combine:

- **Python** for the public API and research ergonomics;
- **Rust** for computationally intensive kernels;
- **Apache Arrow** as the interoperability and memory-layout contract;
- **Polars** as the preferred high-level dataframe implementation;
- **NumPy/SciPy** where mature numerical implementations are more valuable than rewriting established routines;
- **Parquet** as the preferred persistent analytical format;
- **PyO3 + maturin** for Python/Rust integration and binary-wheel distribution.

Performance is a first-class requirement.

Lacuna should avoid Python loops over observations, minimize copies at dataframe boundaries, use parallel Rust kernels where appropriate, stream data where possible, and make benchmark regressions a release-blocking concern.

---

# 2. What Lacuna Is

Lacuna is a **quantitative research validation library**.

Its core object is not a broker, exchange, order, portfolio, or trading algorithm.

Its core objects are closer to:

- observations;
- signals;
- labels;
- forward returns;
- experiments;
- hypotheses;
- validation folds;
- costs;
- robustness tests;
- evidence;
- findings.

The library should help a researcher move through:

```text
IDEA
  │
  ▼
SIGNAL
  │
  ▼
EFFICACY
  │
  ▼
STATISTICAL EVIDENCE
  │
  ▼
LEAKAGE / BIAS CHECKS
  │
  ▼
ROBUSTNESS
  │
  ▼
COST / CAPACITY
  │
  ▼
OUT-OF-SAMPLE VALIDATION
  │
  ▼
AUDIT
```

Lacuna should be useful to:

- retail systematic traders;
- independent quantitative researchers;
- academic researchers;
- small hedge funds;
- prop traders;
- quant developers;
- research teams;
- users of existing backtesting frameworks;
- researchers evaluating externally produced backtests.

---

# 3. What Lacuna Is Not

Scope discipline is essential.

Lacuna should **not** attempt to become all of the following.

## 3.1 Not a broker integration framework

No native order routing in core.

Broker adapters may eventually consume Lacuna results, but brokerage connectivity belongs elsewhere.

## 3.2 Not a full event-driven backtester

LEAN, NautilusTrader and other engines already address this problem.

Lacuna may provide lightweight portfolio transformations needed for diagnostics, but it should not simulate a full exchange.

## 3.3 Not a market-data vendor

Lacuna should define schemas and adapters, not redistribute licensed market data.

## 3.4 Not an alpha marketplace

The library evaluates research. It does not sell signals.

## 3.5 Not a charting platform

Reports should be excellent, but visualization is an output of analysis rather than the product's primary function.

## 3.6 Not an AutoML strategy generator

Lacuna should make it harder to overfit, not industrialize curve fitting.

## 3.7 Not a magical "strategy score"

A composite robustness score can be useful as a summary, but all underlying evidence must remain visible.

The primary output is **evidence and diagnostics**, not false precision.

---

# 4. Design Goals

## 4.1 Correctness first

A fast wrong answer is worthless.

Statistical definitions, temporal semantics, label construction, purging, point-in-time joins, transaction-cost application and annualization conventions must be explicit and tested.

## 4.2 Performance by architecture

Performance must come from the design:

- columnar memory;
- vectorized operations;
- Rust hot paths;
- limited boundary crossings;
- zero-copy interchange where possible;
- cache-friendly access;
- parallel execution;
- streaming;
- careful allocation.

It should not depend on adding optimization later.

## 4.3 Engine independence

Lacuna should work with results originating from any research or backtesting framework.

## 4.4 Progressive disclosure

A beginner should be able to run:

```python
lc.audit(returns)
```

An expert should be able to specify:

```python
lc.validation.block_bootstrap(
    returns,
    method="stationary",
    expected_block_length=20,
    resamples=100_000,
    seed=42,
)
```

## 4.5 Transparent methodology

Every statistic should be inspectable.

A result should know:

- method;
- parameters;
- assumptions;
- sample size;
- effective sample size when applicable;
- random seed;
- input fingerprint;
- warning state.

## 4.6 Composability

Researchers should be able to use individual functions without adopting the entire framework.

## 4.7 Reproducibility

A report should be reproducible from:

- input fingerprints;
- configuration;
- Lacuna version;
- algorithm version;
- random seeds;
- environment metadata.

## 4.8 Minimal mandatory dependency surface

The core installation should remain lean.

Large or specialized features should live behind extras.

---

# 5. Core Design Principles

## Principle 1 — Time is part of the type system

In quantitative research, a value without a clear temporal meaning is dangerous.

Lacuna should distinguish:

- `event_time` — when the underlying event occurred;
- `available_time` — when a researcher could have known it;
- `effective_time` — when a value became economically applicable;
- `revision_time` — when a historical value was revised;
- `label_start` — when a target interval begins;
- `label_end` — when a target interval ends.

These are not interchangeable.

## Principle 2 — Never hide overlap

Overlapping labels are a core source of leakage.

Every label-aware validation splitter must understand label intervals.

## Principle 3 — Prefer residual evidence over headline returns

A strategy CAGR is an outcome.

Lacuna should investigate whether the underlying signal contains information before celebrating the outcome.

## Principle 4 — Treat every research path as a multiple-testing problem

The researcher rarely tried only one idea.

Experiment history should therefore be a first-class concept.

## Principle 5 — Robustness means neighborhoods, not points

A parameter value is not evidence.

A stable neighborhood is more meaningful.

## Principle 6 — Costs are distributions, not constants

Spread, slippage and impact change with instrument, time, volatility, liquidity and size.

Lacuna should support scenarios and uncertainty, not only a single fixed basis-point deduction.

## Principle 7 — Interoperate instead of replacing

Lacuna should accept ordinary data structures and return ordinary structures.

## Principle 8 — Performance features require benchmarks

No optimization claim should be accepted solely because the implementation "looks faster."

---

# 6. High-Level Architecture

```text
                       USER RESEARCH CODE
          pandas / Polars / NumPy / Arrow / backtester
                             │
                             ▼
                  ┌──────────────────────┐
                  │    Python API Layer  │
                  │  ergonomic + typed  │
                  └──────────┬───────────┘
                             │
                      normalization
                             │
                             ▼
                  ┌──────────────────────┐
                  │  Arrow Data Contract │
                  │ arrays / recordsets │
                  └──────────┬───────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
       ┌────────────┐  ┌────────────┐  ┌────────────┐
       │ Rust Core  │  │ Polars Ops │  │ SciPy/NumPy│
       │ hot kernels│  │ lazy/frame │  │ mature math│
       └──────┬─────┘  └──────┬─────┘  └──────┬─────┘
              │               │               │
              └───────────────┼───────────────┘
                              ▼
                  ┌──────────────────────┐
                  │ Structured Results   │
                  │ findings + metrics  │
                  └──────────┬───────────┘
                             │
                   ┌─────────┴─────────┐
                   ▼                   ▼
            Python objects        Report layer
                                  HTML / JSON /
                                  Markdown
```

The architecture should be intentionally hybrid.

Do not rewrite a mature linear algebra routine in Rust merely to say the library is Rust-backed.

Do move operations to Rust when they are:

- large;
- repeated;
- quant-specific;
- difficult to express efficiently with vectorized dataframe operations;
- currently dominated by Python overhead;
- naturally parallel;
- allocation-sensitive.

---

# 7. Recommended Technology Stack

## 7.1 Primary stack

| Layer | Recommendation | Role |
|---|---|---|
| Public API | Python 3.11+ | Research ergonomics |
| Native core | Rust stable, Edition 2024 | Performance-critical algorithms |
| Python/Rust bridge | PyO3 | Native Python extension |
| Wheel build | maturin | Cross-platform Python binary packaging |
| DataFrame | Polars | Preferred high-level columnar computation |
| Memory interchange | Apache Arrow C Data / C Stream interfaces | Low-copy interoperability |
| Array API | NumPy | Universal numeric compatibility |
| Statistics | SciPy | Mature distributions/tests/linear algebra where appropriate |
| Storage | Parquet | Persistent analytical datasets |
| Local SQL | DuckDB adapter | Optional query/interoperability layer |
| Embedded query engine | DataFusion adapter, later | Optional Rust-native query extension |
| Parallelism | Rayon | Rust CPU parallelism |
| Serialization | serde | Rust configs/results |
| Python package manager | uv | Reproducible dev environments |
| Python lint/format | Ruff | Fast unified linting/formatting |
| Python tests | pytest + Hypothesis | Unit + property testing |
| Rust tests | cargo test / cargo nextest | Native testing |
| Rust benchmarks | Criterion.rs | Statistical microbenchmarks |
| CI | GitHub Actions | Test/build/release matrix |
| Documentation | MkDocs Material or Sphinx | User/developer docs |
| API typing | py.typed + strict annotations | Editor/type-checking support |

## 7.2 Why Python remains the public language

Quant researchers overwhelmingly benefit from the Python ecosystem:

- notebooks;
- NumPy;
- SciPy;
- scikit-learn;
- Polars;
- pandas;
- plotting;
- data-vendor SDKs;
- backtesting frameworks.

Forcing researchers to use Rust directly would dramatically reduce adoption.

The correct architecture is:

> **Python outside, Rust inside.**

## 7.3 Why Rust rather than C++ for the native core

Rust provides:

- native performance;
- excellent concurrency primitives;
- strong memory safety;
- good package tooling;
- good Arrow ecosystem support;
- mature Python integration through PyO3;
- easy binary-wheel packaging through maturin.

C++ remains appropriate for many quant systems, but a new open-source Python library receives substantial maintainability benefits from Rust.

## 7.4 Why Arrow is the data contract

Arrow is more important to Lacuna than any dataframe brand.

Its columnar representation supports:

- contiguous analytical buffers;
- vectorization;
- cache locality;
- language-independent schemas;
- C ABI interchange;
- record-batch streaming;
- reduced serialization;
- low- or zero-copy exchange where compatible.

The design goal should be:

```text
Polars ─┐
pandas ─┼──► Arrow-compatible boundary ─► Lacuna kernel
PyArrow ┤
DuckDB ─┤
NumPy ──┘
```

rather than:

```text
everything ─► bespoke Lacuna DataFrame ─► regret
```

## 7.5 Why Polars should be preferred over pandas internally

Polars should be the preferred dataframe layer because its architecture is aligned with Lacuna's requirements:

- Rust implementation;
- columnar execution;
- parallel execution;
- lazy query optimization;
- streaming support;
- Arrow interoperability;
- efficient group/window operations.

pandas support remains mandatory for adoption, but pandas should be an **edge compatibility format**, not the internal performance contract.

## 7.6 Why DuckDB is optional rather than core

DuckDB is excellent for:

- local Parquet querying;
- joins;
- filtering;
- exploratory SQL;
- dataset extraction.

However, Lacuna is not a database.

Making DuckDB mandatory would increase architectural coupling without improving every workflow.

Recommended:

```bash
pip install "lacuna[duckdb]"
```

## 7.7 Why DataFusion is optional

DataFusion becomes interesting if Lacuna eventually needs:

- custom Rust query operators;
- distributed/object-store execution;
- embedded analytical plans;
- native query optimization around Lacuna-specific operations.

It should not be a v0.1 dependency.

The initial system can achieve substantial performance through Polars + direct Rust kernels.

## 7.8 Dependency tiers

### Core

```text
polars
numpy
typing-extensions   # only if supported Python range needs it
lacuna._native      # compiled Rust extension
```

### Statistics extra

```text
scipy
```

### Reporting extra

```text
plotly
jinja2
```

### pandas extra

```text
pandas
pyarrow             # if needed for robust interchange path
```

### ML extra

```text
scikit-learn
```

### DuckDB extra

```text
duckdb
```

The final exact dependency split should follow profiling and compatibility testing.

---

# 8. Performance Architecture

Performance should be treated as a product feature.

## 8.1 Performance rules

### Rule A — No Python per-row loops in core analysis

Any operation whose complexity scales with observations must be vectorized, delegated to Polars, NumPy/SciPy, or implemented natively.

### Rule B — Cross the Python/Rust boundary at coarse granularity

Bad:

```python
for row in rows:
    native.process_row(row)
```

Good:

```python
native.process_signal_matrix(values, dates, assets, config)
```

FFI overhead should be amortized over large operations.

### Rule C — Avoid materialization until necessary

Prefer:

```python
pl.scan_parquet(...)
```

over eagerly reading all data.

### Rule D — Favor columnar traversal

Signal research is mostly:

- scans;
- ranks;
- group reductions;
- rolling statistics;
- sort/group operations;
- bootstrap reductions.

The data representation should optimize those operations.

### Rule E — Avoid unnecessary dtype inflation

Many large market datasets can store:

- IDs as categorical/dictionary encodings;
- flags as booleans;
- group IDs as 32-bit integers;
- prices/returns as `float64` by default;
- selected high-volume auxiliary columns as `float32` only where precision analysis permits.

Precision policy must be explicit.

### Rule F — Allocate once where possible

Bootstrap and resampling kernels should reuse scratch buffers.

### Rule G — Batch results

Returning millions of Python objects defeats the purpose of a native core.

Return arrays, frames or compact structured summaries.

---

## 8.2 Native-kernel candidates

Good initial Rust targets:

- cross-sectional rank IC;
- grouped IC;
- quantile assignment;
- quantile forward-return aggregation;
- turnover;
- signal autocorrelation;
- decay curves;
- block bootstrap;
- stationary bootstrap;
- permutation tests;
- parameter-grid reductions;
- combinatorial CV index generation;
- purging/embargo interval overlap;
- path-independent transaction-cost sweeps;
- regime cross-tab reductions;
- fast temporal leakage checks;
- content fingerprinting.

Potential later candidates:

- rolling rank transforms;
- neutralization regressions;
- large-panel winsorization;
- specialized covariance estimators;
- PBO/CSCV;
- SPA/reality-check bootstrap;
- options-surface diagnostics.

---

## 8.3 Operations that should initially remain in mature libraries

Do not rewrite these without evidence:

- BLAS/LAPACK-heavy matrix algebra;
- generic optimization;
- probability distribution functions;
- well-tested statistical distributions;
- standard regressions;
- SVD/eigendecomposition;
- standard hypothesis tests already efficiently implemented in SciPy.

---

## 8.4 Zero-copy policy

"Zero copy" should be a goal, not a dishonest guarantee.

Some conversions necessarily allocate because:

- null representations differ;
- chunking differs;
- dtypes differ;
- data must be sorted;
- alignment differs;
- an operation requires mutable scratch space.

Every adapter should document whether a path is:

- zero-copy;
- potentially zero-copy;
- one-copy;
- materializing.

A debug mode should optionally expose copy diagnostics.

Example:

```python
with lc.debug.memory_trace():
    result = lc.signal.ic(frame)
```

Potential output:

```text
Input: Polars DataFrame
Arrow export: zero-copy
Signal values: zero-copy
Asset dictionary normalization: allocated 18.2 MB
IC output: allocated 12 KB
```

This is a later feature, but the architecture should permit it.

---

## 8.5 Threading

Native Rust kernels should release the Python GIL while computing.

Parallel work should use Rayon where it provides meaningful speedup.

Parallelization dimensions include:

- date;
- bootstrap replicate;
- parameter combination;
- CV split;
- universe;
- regime;
- horizon.

Avoid parallelizing tiny groups.

### Oversubscription

A major performance risk is:

```text
Polars threads
× Rayon threads
× BLAS threads
```

Lacuna should expose a coherent thread budget.

Example:

```python
lc.Config.set_threads(12)
```

or:

```bash
LACUNA_NUM_THREADS=12
```

Documentation should recommend controlling BLAS threads for highly nested workloads.

---

## 8.6 Deterministic parallel randomness

Resampling must remain reproducible regardless of thread scheduling.

Do not use a single shared RNG whose sequence depends on execution order.

Instead:

```text
root_seed
   │
   ├── deterministic seed for replicate 0
   ├── deterministic seed for replicate 1
   ├── deterministic seed for replicate 2
   └── ...
```

A counter-based or deterministically split RNG design is preferred.

---

## 8.7 Streaming

Large studies should not require every derived intermediate to reside in memory.

Streaming-friendly operations:

- date-by-date IC;
- group aggregates;
- histogram accumulation;
- cost stress summaries;
- regime summaries;
- universe validation;
- point-in-time checks.

Algorithms requiring global sorting or random access may materialize explicitly.

The API should never silently convert a 500 GB lazy dataset into a 500 GB in-memory frame.

---

# 9. Canonical Data Model

Lacuna should avoid a proprietary dataframe while still defining **semantic schemas**.

## 9.1 Instrument identifier

Never treat ticker as permanent identity.

Canonical:

```text
instrument_id
```

Ticker should be metadata:

```text
symbol
exchange
currency
valid_from
valid_to
```

The library should allow strings, integers or Arrow dictionary values as IDs.

## 9.2 Observation schema

Minimum:

| Column | Meaning |
|---|---|
| `time` | observation/effective timestamp |
| `instrument` | stable instrument identifier |
| `value` | numeric observation |

Optional:

| Column | Meaning |
|---|---|
| `available_time` | earliest usable timestamp |
| `group` | sector/country/etc. |
| `weight` | observation weight |
| `universe` | eligibility flag |
| `source` | provenance |
| `revision_time` | revision timestamp |

## 9.3 SignalFrame

Conceptual schema:

```text
time: timestamp
instrument: id
signal: float64
[group...]
[weight]
```

A `SignalFrame` is semantic validation over ordinary columnar data, not a custom dataframe.

## 9.4 PriceFrame

```text
time
instrument
open
high
low
close
volume
```

Only required columns should be validated for a requested calculation.

## 9.5 LabelFrame

```text
observation_time
label_start
label_end
instrument
label
```

The explicit interval is crucial for purging.

## 9.6 ReturnFrame

```text
time
instrument
horizon
forward_return
```

or wide form where useful:

```text
time
instrument
fwd_1d
fwd_5d
fwd_20d
```

Internal kernels may choose whichever layout is optimal.

## 9.7 TradeFrame

Minimum recommended schema:

```text
decision_time
execution_time
instrument
side
quantity
price
reference_price
```

Optional:

```text
bid
ask
mid
volume
adv
volatility
commission
borrow_rate
venue
order_id
strategy_id
```

## 9.8 ExperimentTrial

Every meaningful model/strategy trial should be representable as:

```text
trial_id
created_at
family
parameters
sample_start
sample_end
universe
metric
metric_value
selected
input_hash
code_hash
```

This is foundational to multiple-testing analysis.

---

# 10. Core Package Structure

Recommended user-facing package:

```text
lacuna/
├── __init__.py
├── config.py
├── types.py
├── exceptions.py
│
├── signal/
│   ├── ic.py
│   ├── quantiles.py
│   ├── decay.py
│   ├── turnover.py
│   ├── neutralize.py
│   └── transform.py
│
├── labels/
│   ├── forward_returns.py
│   ├── intervals.py
│   └── events.py
│
├── cv/
│   ├── walk_forward.py
│   ├── purged.py
│   ├── combinatorial.py
│   └── embargo.py
│
├── validation/
│   ├── bootstrap.py
│   ├── permutation.py
│   ├── sharpe.py
│   ├── multiple_testing.py
│   ├── overfitting.py
│   └── stability.py
│
├── regime/
│   ├── definitions.py
│   ├── analysis.py
│   └── sensitivity.py
│
├── costs/
│   ├── models.py
│   ├── stress.py
│   ├── impact.py
│   └── capacity.py
│
├── bias/
│   ├── point_in_time.py
│   ├── leakage.py
│   ├── survivorship.py
│   └── universe.py
│
├── audit/
│   ├── audit.py
│   ├── findings.py
│   ├── rules.py
│   └── score.py
│
├── report/
│   ├── html.py
│   ├── markdown.py
│   ├── json.py
│   └── plots.py
│
├── adapters/
│   ├── pandas.py
│   ├── polars.py
│   ├── arrow.py
│   ├── numpy.py
│   ├── duckdb.py
│   └── sklearn.py
│
├── experiment/
│   ├── trial.py
│   ├── registry.py
│   └── fingerprint.py
│
└── _native.*     # compiled extension
```

Rust workspace:

```text
rust/
├── lacuna-core/
├── lacuna-arrow/
├── lacuna-signal/
├── lacuna-resample/
├── lacuna-cv/
├── lacuna-costs/
└── lacuna-python/
```

Do not split crates prematurely.

A practical starting workspace may use only:

```text
lacuna-core
lacuna-python
```

and split once compile time or ownership boundaries justify it.

---

# 11. Signal Research

The signal module should answer:

> Does this feature contain predictive information?

## 11.1 Information coefficient

Support:

- Pearson IC;
- Spearman rank IC;
- weighted variants;
- per-period cross-sectional IC;
- grouped IC;
- pooled IC with warnings about interpretation.

Example:

```python
result = lc.signal.ic(
    signal,
    forward_returns,
    method="spearman",
    by="date",
)
```

Result:

```text
mean_ic
median_ic
std_ic
ic_ir
t_stat
positive_fraction
n_periods
n_observations
```

## 11.2 Quantile analysis

```python
q = lc.signal.quantiles(
    signal,
    forward_returns,
    quantiles=10,
)
```

Metrics:

- mean return by quantile;
- median return;
- quantile spread;
- monotonicity;
- bootstrap confidence intervals;
- sample counts;
- turnover.

## 11.3 Monotonicity

Do not define monotonicity as a vague visual score.

Possible metrics:

- Spearman correlation between quantile number and mean forward return;
- fraction of adjacent quantile pairs ordered correctly;
- isotonic fit error.

Expose components rather than only one metric.

## 11.4 Signal decay

Evaluate predictive power at multiple horizons:

```python
lc.signal.decay(
    signal,
    prices,
    horizons=["1D", "2D", "5D", "10D", "20D"],
)
```

Outputs:

- IC by horizon;
- spread return by horizon;
- half-life estimate where meaningful;
- turnover implications.

## 11.5 Turnover

Support:

- rank turnover;
- top/bottom quantile membership turnover;
- portfolio-weight turnover;
- signal autocorrelation.

## 11.6 Neutralization

Support residualizing signal against:

- sector;
- industry;
- country;
- beta;
- size;
- volatility;
- user-specified exposures.

Example:

```python
neutral = lc.signal.neutralize(
    signal,
    exposures=["sector", "log_market_cap", "beta_1y"],
    by="date",
)
```

Initial implementation can use weighted least squares through mature numerical libraries.

Large repeated cross-sectional regressions may later receive a specialized native kernel.

---

# 12. Forward Returns and Labels

Forward-return construction is deceptively dangerous and deserves first-class implementation.

## 12.1 Basic API

```python
labels = lc.labels.forward_returns(
    prices,
    horizons=["1D", "5D", "20D"],
    price="close",
)
```

## 12.2 Explicit execution semantics

A signal observed at the close cannot normally earn the same closing price unless the research design explicitly assumes it was known before that price formed.

Therefore the API should support:

```python
lc.labels.forward_returns(
    prices,
    signal_time="close",
    entry="next_open",
    exit="close",
    horizon="5D",
)
```

## 12.3 Delisting returns

If data supplies delisting outcomes, Lacuna must allow inclusion.

If delisting behavior is unknown, the audit should warn.

## 12.4 Corporate actions

The library should not guess whether source prices are adjusted.

Metadata should state:

```text
price_adjustment:
    raw
    split_adjusted
    total_return_adjusted
    unknown
```

Unknown should generate a warning in relevant analyses.

---

# 13. Financial Cross-Validation

Generic random K-fold validation is frequently inappropriate for financial data.

Lacuna should make safe temporal splitting easy.

## 13.1 Walk-forward

```python
cv = lc.cv.WalkForward(
    train="5Y",
    test="1Y",
    step="6M",
    mode="expanding",
)
```

Support:

- expanding;
- rolling;
- anchored;
- fixed calendar dates.

## 13.2 Purged K-fold

```python
cv = lc.cv.PurgedKFold(
    n_splits=5,
    embargo="5D",
)
```

Purging removes training observations whose label intervals overlap the test interval.

## 13.3 Embargo

Embargo creates additional temporal separation after a test region where required by the research design.

## 13.4 Combinatorial purged cross-validation

Later versions should support CPCV.

The API must expose generated paths rather than hiding them.

## 13.5 Visualization

Every splitter should provide a fold visualization.

```text
time ─────────────────────────────────────────►

Fold 1
TRAIN ███████████████
PURGE                ░
TEST                  ████
EMBARGO                   ░

Fold 2
TRAIN ███████████████████
PURGE                    ░
TEST                      ████
```

Temporal leakage becomes far easier to understand when visible.

---

# 14. Statistical Validation

## 14.1 Bootstrap

Methods:

- IID bootstrap;
- moving block bootstrap;
- circular block bootstrap;
- stationary bootstrap.

For financial returns, dependent bootstrap variants should be first-class.

Example:

```python
ci = lc.validation.bootstrap(
    returns,
    statistic="mean",
    method="stationary",
    expected_block_length=20,
    resamples=50_000,
    seed=7,
)
```

## 14.2 Permutation tests

Useful for testing whether a signal/label relation exceeds an appropriate null.

Permutation scheme matters.

Support:

- unrestricted permutation;
- within-date permutation;
- within-group permutation;
- block permutation;
- sign-flip where justified.

## 14.3 Sharpe uncertainty

Provide:

- observed Sharpe;
- standard error;
- Probabilistic Sharpe Ratio;
- Deflated Sharpe Ratio;
- minimum track-record length where method assumptions are satisfied.

## 14.4 Robust confidence intervals

Where possible, offer:

- analytical interval;
- bootstrap interval;
- block-bootstrap interval.

The report should not imply that an IID analytical interval is sufficient for autocorrelated data.

## 14.5 Effective sample size

When observations are correlated or clustered, raw observation count can dramatically overstate evidence.

Lacuna should expose:

```text
n_raw
n_effective
```

when a defensible estimate is available.

---

# 15. Multiple-Testing and Backtest-Overfitting Controls

This should become a signature capability.

## 15.1 Trial registry

A user can explicitly register tests:

```python
registry = lc.ExperimentRegistry("momentum-study")

for lookback in [20, 40, 60, 80, 120, 180, 252]:
    result = run_strategy(lookback)
    registry.record(
        parameters={"lookback": lookback},
        metric=result.sharpe,
    )
```

Lacuna then knows the winning strategy was selected from multiple attempts.

## 15.2 Corrections

Support common corrections where applicable:

- Bonferroni;
- Holm;
- Benjamini-Hochberg FDR;
- Benjamini-Yekutieli where dependence assumptions warrant;
- user-provided effective number of trials.

## 15.3 Deflated Sharpe Ratio

DSR should be treated as a core validation statistic.

Inputs and assumptions must be reported.

## 15.4 Probability of Backtest Overfitting

Implement CSCV/PBO as a later core milestone.

Output should include:

- number of combinations;
- relative out-of-sample rank;
- logit distribution;
- estimated PBO;
- sensitivity to partitioning.

## 15.5 White Reality Check / Hansen SPA

These are advanced methods and should be added only with careful validation against reference implementations.

They belong in the long-term scope because they address data-snooping across strategy families.

---

# 16. Parameter Stability

A successful point estimate is weak evidence.

Lacuna should explore neighborhoods.

## 16.1 Parameter surface

```python
surface = lc.validation.parameter_surface(
    evaluate=my_strategy,
    grid={
        "lookback": range(40, 121, 5),
        "holding": [1, 3, 5, 10],
    },
)
```

## 16.2 Stability metrics

Possible outputs:

- neighborhood median;
- neighborhood dispersion;
- fraction profitable;
- fraction with positive IC;
- local gradient;
- curvature;
- peak isolation;
- plateau width;
- rank persistence.

## 16.3 Peak-isolation warning

Example:

```text
PARAMETER ROBUSTNESS

Best:
lookback=63
holding=5
Sharpe=2.14

Local median Sharpe: 0.48
Best / local median: 4.46x
Peak width: 1 grid cell

Finding: HIGHLY ISOLATED OPTIMUM
Severity: HIGH
```

This is far more useful than merely plotting a heatmap.

## 16.4 Continuous perturbation

For continuous parameters, random perturbation around the selected optimum can complement grid tests.

---

# 17. Regime Analysis

Lacuna should allow arbitrary regimes rather than hardcoding macro beliefs.

## 17.1 Built-in regime primitives

Possible convenience definitions:

- market trend;
- realized volatility;
- implied volatility;
- cross-sectional dispersion;
- rates trend;
- liquidity;
- drawdown state.

## 17.2 User-defined regime

```python
study.by_regime(
    {
        "high_vol": vix > vix.quantile(0.75),
        "low_vol": vix < vix.quantile(0.25),
    }
)
```

## 17.3 Outputs

For each regime:

- IC;
- spread;
- Sharpe;
- drawdown;
- hit rate;
- turnover;
- sample count;
- effective sample size;
- confidence interval.

## 17.4 Regime concentration

Quantify whether a strategy's total performance is disproportionately generated by a narrow regime.

Example:

```text
72% of total P&L occurred in 14% of observations.
```

That should trigger a concentration warning.

---

# 18. Transaction-Cost and Capacity Analysis

The goal is not perfect market-impact simulation.

The goal is to answer:

> How fragile is the strategy to plausible trading friction?

## 18.1 Cost model interface

```python
class CostModel(Protocol):
    def estimate(self, trades, market) -> CostEstimate: ...
```

Built-ins:

- fixed commission;
- half-spread;
- full-spread;
- fixed slippage;
- percentage slippage;
- volatility-scaled slippage;
- participation-rate impact;
- square-root impact;
- borrow cost.

## 18.2 Stress grid

```python
stress = lc.costs.stress(
    strategy,
    spread_bps=[0, 2, 5, 10, 20],
    slippage_bps=[0, 2, 5, 10],
)
```

Output:

```text
                     Slippage
Spread        0      2      5      10
  0          1.80   1.71   1.53   1.12
  2          1.72   1.63   1.45   1.03
  5          1.55   1.46   1.28   0.86
 10          1.24   1.15   0.97   0.54
 20          0.75   0.66   0.48   0.09
```

## 18.3 Break-even cost

Compute the implied all-in trading cost that drives:

- expected alpha to zero;
- Sharpe below a user threshold;
- CAGR below a user threshold.

## 18.4 Capacity curve

Given volume and market assumptions:

```text
capital
participation
impact
net return
net Sharpe
```

Return a curve rather than one capacity number.

## 18.5 Uncertainty

Cost assumptions should support scenarios:

```python
lc.costs.Scenario(
    spread_multiplier=(1.0, 1.5, 2.0),
    volatility_multiplier=(1.0, 1.3),
)
```

---

# 19. Point-in-Time Correctness and Bias Detection

This should become another core differentiator.

## 19.1 As-of joins

Provide a safe primitive:

```python
lc.bias.asof_join(
    left=observations,
    right=fundamentals,
    left_time="decision_time",
    right_time="available_time",
    by="instrument",
)
```

The default must never choose data unavailable at decision time.

## 19.2 Availability-time semantics

For a filing:

```text
fiscal_period_end = 2026-03-31
filing_date       = 2026-05-08
available_time    = 2026-05-08 16:30:00 ET
```

A March value does not become usable in March simply because it describes March.

## 19.3 Revisions

Fundamental/economic data may be revised.

Support:

```text
observation_time
available_time
revision_time
value
```

Point-in-time selection chooses the version available at the research timestamp.

## 19.4 Future-data detection

If:

```text
available_time > decision_time
```

the observation is impossible.

The audit should report both count and materiality.

## 19.5 Survivorship

A universe supplied only as current members cannot reproduce historical investability.

Lacuna should detect suspicious cases where possible and otherwise record:

```text
survivorship_status = "unknown"
```

Unknown is not pass.

## 19.6 Universe drift

Test strategy behavior under:

- full source universe;
- liquidity threshold changes;
- market-cap thresholds;
- exchanges;
- sectors;
- minimum price;
- random universe subsamples.

## 19.7 Index membership

Membership should be timestamped:

```text
instrument
index
valid_from
valid_to
```

---

# 20. The Audit Engine

`lacuna.audit()` should become the iconic interface.

## 20.1 Basic usage

```python
report = lc.audit(
    returns=returns,
    signals=signals,
    trades=trades,
    trials=registry,
)
```

Inputs are optional.

Available checks depend on supplied evidence.

## 20.2 Finding states

Use:

```text
PASS
WARN
FAIL
UNKNOWN
NOT_APPLICABLE
```

Do not convert absence of evidence into PASS.

## 20.3 Severity

Separate result state from severity:

```text
info
low
medium
high
critical
```

Example:

```text
State: WARN
Severity: HIGH
Finding: Trial history is unavailable; multiple-testing risk cannot be estimated.
```

## 20.4 Audit categories

### Statistical evidence

- confidence intervals;
- PSR;
- DSR;
- bootstrap;
- minimum sample support.

### Robustness

- subperiod;
- parameter;
- universe;
- horizon;
- regime.

### Bias

- time leakage;
- label overlap;
- look-ahead;
- survivorship;
- revision handling.

### Execution

- cost sensitivity;
- turnover;
- liquidity;
- capacity.

### Research process

- trial history;
- selection procedure;
- out-of-sample isolation;
- code/data fingerprinting.

## 20.5 Composite robustness score

A score may be exposed for convenience:

```text
Robustness: 72 / 100
```

But it must never be the only output.

The score must provide:

- component weights;
- missing-evidence penalty policy;
- versioned scoring model;
- raw component metrics.

Prefer:

```text
Statistical evidence    18/25
Robustness              19/25
Bias controls           20/25
Execution realism       15/25
```

over an unexplained number.

## 20.6 Audit example

```text
LACUNA AUDIT
────────────────────────────────────────────────

STATISTICAL EVIDENCE
Bootstrap mean return                   PASS
Probabilistic Sharpe                    PASS
Deflated Sharpe                         WARN
Effective sample size                   PASS

ROBUSTNESS
Temporal stability                      PASS
Parameter stability                     WARN
Universe stability                      PASS
Regime concentration                    WARN

BIAS
Future-data check                       PASS
Label overlap                           FAIL
Survivorship handling                   UNKNOWN
Point-in-time fundamentals              PASS

EXECUTION
2× cost stress                          PASS
5× cost stress                          FAIL
Turnover                                WARN
Capacity evidence                       UNKNOWN

RESEARCH PROCESS
Out-of-sample isolation                 PASS
Trial history                           WARN
Reproducible seed                       PASS

────────────────────────────────────────────────
Overall robustness                      72 / 100
Critical failures                       1
High-severity warnings                  2
Unknown checks                          2
```

---

# 21. Reporting

Reports should separate computation from presentation.

## 21.1 Result objects first

Every analysis returns structured data.

Example:

```python
result.metrics
result.findings
result.tables
result.metadata
```

A report renderer consumes these.

## 21.2 Output formats

Core:

- Python object;
- JSON;
- Markdown.

Optional reporting extra:

- HTML;
- interactive charts;
- notebook rendering.

Potential later:

- PDF.

## 21.3 Reports must remain machine-readable

HTML is not the source of truth.

The underlying audit should serialize to a versioned JSON schema.

## 21.4 Plot data

Every rendered chart should expose its source table.

A user should be able to do:

```python
report.table("ic_decay")
```

rather than scraping a plot.

---

# 22. Adapters and Interoperability

Lacuna succeeds if researchers can add it to existing systems with little friction.

## 22.1 Polars

Preferred path.

Accept:

- `pl.DataFrame`;
- `pl.LazyFrame`;
- `pl.Series`.

Where possible, preserve lazy execution until a native kernel requires materialization.

## 22.2 pandas

Accept:

- `pd.DataFrame`;
- `pd.Series`.

Convert through an Arrow-compatible route where feasible.

Document memory behavior.

## 22.3 NumPy

Accept arrays for lower-level functions:

```python
lc.validation.probabilistic_sharpe(returns_np)
```

## 22.4 PyArrow

Accept:

- `Table`;
- `RecordBatch`;
- `RecordBatchReader`.

## 22.5 DuckDB

Optional adapter should support DuckDB Arrow result streams without requiring pandas materialization.

## 22.6 Backtesting frameworks

Do not hard-depend on them.

Provide lightweight conversion helpers:

```text
lacuna.adapters.vectorbt
lacuna.adapters.lean
lacuna.adapters.nautilus
```

only when community demand justifies maintenance.

CSV/Parquet remains the universal fallback.

---

# 23. Caching, Provenance, and Reproducibility

## 23.1 Study fingerprint

A study fingerprint should incorporate:

- input fingerprint;
- method name;
- method version;
- parameters;
- Lacuna version;
- relevant configuration.

Use a fast content hash such as BLAKE3 for internal IDs if implemented in Rust.

## 23.2 Cache

Cache should be optional.

Potential layout:

```text
~/.cache/lacuna/
    objects/
    reports/
    metadata/
```

## 23.3 Never silently cache mutable user objects

Cache only after serialization/fingerprinting establishes identity.

## 23.4 Provenance record

Example:

```json
{
  "lacuna_version": "0.3.0",
  "method": "signal.ic",
  "method_version": 2,
  "input_hash": "...",
  "parameters": {
    "method": "spearman",
    "horizon": "5D"
  },
  "seed": 42,
  "created_at": "..."
}
```

## 23.5 Reproducibility bundle

Later:

```python
report.bundle("study.lacuna")
```

could package:

- audit JSON;
- config;
- metadata;
- environment lock;
- optional small derived datasets.

Do not package proprietary source data by default.

---

# 24. Parallelism and Execution

## 24.1 Execution planner

Lacuna does not initially need a full query planner.

Simple dispatch is enough:

```text
small data
    └── vectorized Python/NumPy

columnar dataframe operation
    └── Polars

quant-specific heavy kernel
    └── Rust

large lazy scan
    └── Polars streaming

SQL extraction
    └── optional DuckDB/DataFusion adapter
```

## 24.2 Thresholds

Performance dispatch thresholds must be benchmark-derived, not guessed.

For example, a small bootstrap may be faster in NumPy due to FFI setup while a huge block bootstrap may strongly favor Rust.

Benchmarks determine the crossover.

## 24.3 Thread configuration

```python
lc.configure(
    threads="auto",
    memory_limit="16GB",
)
```

Potential environment variables:

```text
LACUNA_NUM_THREADS
LACUNA_CACHE_DIR
LACUNA_MEMORY_LIMIT
LACUNA_LOG
```

---

# 25. Numerical Correctness

## 25.1 Default floating point

Default numerical analytics:

```text
float64
```

Finance metrics can be sensitive to small numerical differences, and the memory savings of `float32` usually do not justify making it the default.

## 25.2 Missing values

NaN and Arrow null are not semantically identical.

Every public function must define:

```text
null_policy
nan_policy
inf_policy
```

Possible policies:

- `raise`;
- `drop`;
- `propagate`;
- method-specific handling.

Silent behavior is unacceptable.

## 25.3 Degrees of freedom

Variance and standard-deviation definitions must explicitly document `ddof`.

## 25.4 Annualization

Annualization must not assume `252` universally.

API:

```python
lc.performance.sharpe(
    returns,
    periods_per_year=252,
)
```

or infer only when frequency metadata is reliable.

## 25.5 Timestamp normalization

Use timezone-aware timestamps where the source requires them.

Never silently strip timezone information from intraday data.

---

# 26. Plugin Architecture

Lacuna should eventually support third-party checks.

## 26.1 Audit rule protocol

Conceptually:

```python
class AuditRule(Protocol):
    name: str

    def applicable(self, context) -> bool: ...
    def run(self, context) -> Finding: ...
```

## 26.2 Cost model protocol

```python
class CostModel(Protocol):
    def estimate(self, trades, market) -> CostEstimate: ...
```

## 26.3 Regime provider

```python
class RegimeProvider(Protocol):
    def classify(self, data) -> RegimeFrame: ...
```

## 26.4 Entry points

Use Python package entry points for discoverable extensions.

Plugins must never be imported automatically in a way that executes untrusted code without user action.

---

# 27. Optional Options-Research Extension

A future `lacuna-options` package could address a second major gap: empirical options research.

It should remain separate from v0.1.

## 27.1 Scope

- normalized chain schema;
- IV calculation adapter;
- Greeks adapter;
- forwards;
- moneyness;
- delta buckets;
- skew;
- term structure;
- SVI fitting;
- arbitrage diagnostics;
- IV/RV spread;
- volatility risk premium;
- event premium;
- delta-hedged returns;
- surface residuals;
- fair-volatility residual models.

## 27.2 Chain schema

```text
time
instrument
underlying
expiration
strike
option_type
bid
ask
mid
underlying_price
rate
dividend
iv
delta
gamma
vega
theta
open_interest
volume
```

## 27.3 Empirical residual

A defining Lacuna workflow:

```text
Observed IV
    -
Expected IV conditional on comparable states
    =
Residual / dislocation
```

Then validate whether residuals predict:

- IV mean reversion;
- delta-hedged option P&L;
- future realized volatility;
- straddle returns;
- skew normalization.

---

# 28. Python API Design

## 28.1 Functional API

Every major capability should be available functionally.

```python
ic = lc.signal.ic(signal, returns)
```

## 28.2 Study API

Higher-level workflow:

```python
study = lc.SignalStudy(
    signal=signal,
    prices=prices,
)

study.ic()
study.quantiles()
study.decay()
study.robustness()
study.audit()
```

## 28.3 Immutable result objects

Result objects should behave as immutable value objects where practical.

This reduces hidden state and improves reproducibility.

## 28.4 Explicit configuration

Avoid module-level magic.

Bad:

```python
lc.set_magic_mode(True)
```

Prefer scoped config:

```python
with lc.config(threads=8, seed=42):
    result = study.audit()
```

## 28.5 Strong typing

Ship `py.typed`.

Public functions should be thoroughly annotated.

Typing should recognize common inputs without becoming unusably complex.

---

# 29. CLI Design

A small CLI can make Lacuna useful outside notebooks.

## 29.1 Audit

```bash
lacuna audit \
  --returns returns.parquet \
  --trades trades.parquet \
  --out report.html
```

## 29.2 Signal analysis

```bash
lacuna signal \
  --signal factor.parquet \
  --prices prices.parquet \
  --horizon 5D \
  --out factor-report.html
```

## 29.3 Validate dataset

```bash
lacuna data-check fundamentals.parquet \
  --decision-time decision_time \
  --available-time available_time
```

## 29.4 Benchmark

Developers:

```bash
lacuna bench
```

This can run a lightweight machine-local suite, separate from CI benchmarks.

---

# 30. Repository Layout

Recommended monorepo:

```text
lacuna/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   ├── wheels.yml
│   │   ├── benchmarks.yml
│   │   └── release.yml
│   └── ISSUE_TEMPLATE/
│
├── python/
│   └── lacuna/
│       ├── ...
│       └── py.typed
│
├── rust/
│   ├── lacuna-core/
│   └── lacuna-python/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── statistical/
│   ├── property/
│   └── regression/
│
├── benches/
│   ├── rust/
│   ├── python/
│   └── datasets/
│
├── docs/
│   ├── getting-started/
│   ├── concepts/
│   ├── api/
│   ├── methodology/
│   └── performance/
│
├── examples/
│   ├── factor_research.py
│   ├── purged_cv.py
│   ├── strategy_audit.py
│   └── point_in_time.py
│
├── pyproject.toml
├── Cargo.toml
├── Cargo.lock
├── uv.lock
├── rust-toolchain.toml
├── README.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── CHANGELOG.md
└── LICENSE files
```

---

# 31. Testing Strategy

Quant software requires more than ordinary unit tests.

## 31.1 Unit tests

Every public statistic.

## 31.2 Reference tests

Compare Lacuna outputs against:

- analytically known results;
- published examples;
- trusted SciPy/NumPy implementations;
- R implementations where useful;
- hand-computed miniature fixtures.

## 31.3 Property-based testing

Hypothesis is ideal for invariants.

Examples:

### Rank invariance

For strictly monotonic transform `f`:

```text
SpearmanIC(x, y) == SpearmanIC(f(x), y)
```

within defined tie behavior.

### Cost monotonicity

Increasing non-negative transaction costs must not increase net P&L in a path-independent cost model.

### Purging

No training label interval may overlap a test label interval after purging.

### Quantile conservation

Every valid observation should belong to exactly one quantile unless excluded by documented tie/minimum-size rules.

## 31.4 Statistical simulation tests

Generate synthetic data where true behavior is known.

Examples:

- zero-alpha null;
- known cross-sectional correlation;
- AR(1) returns;
- clustered labels;
- planted regime dependence;
- planted look-ahead leakage.

These tests catch conceptually wrong implementations that pass ordinary examples.

## 31.5 Differential testing

Where two independent implementations exist, compare them.

For example:

```text
Rust bootstrap
vs
slow Python reference bootstrap
```

on deterministic small fixtures.

## 31.6 Fuzzing

Rust parsers, interval logic and schema conversion paths should receive fuzz testing.

---

# 32. Benchmarking and Performance Regression

Performance is a release criterion.

## 32.1 Benchmark layers

### Rust microbenchmarks

Criterion.rs:

- rank IC kernel;
- interval purge;
- bootstrap;
- quantile assignment;
- turnover;
- PBO components.

### Python end-to-end benchmarks

Use ASV or a lightweight dedicated benchmark runner for:

- pandas input;
- Polars input;
- Arrow input;
- data conversion;
- complete SignalStudy.

## 32.2 Dataset scales

Benchmark at multiple sizes.

Example:

```text
Small      100k rows
Medium       5M rows
Large       50M rows
XL          250M rows
```

XL can run only on scheduled CI/hardware.

## 32.3 Performance budgets

Avoid arbitrary promises such as "10M rows in one second."

Use relative budgets:

- no >10% regression in core kernel throughput without explicit approval;
- no >10% regression in peak memory for stable benchmark cases without explanation;
- no accidental Python-object explosion;
- no new mandatory copy on preferred Arrow/Polars input path.

Thresholds should account for benchmark noise.

## 32.4 Measure memory as well as time

A 2× faster function that uses 10× RAM may be unacceptable.

Track:

- wall time;
- CPU time;
- peak RSS;
- allocations;
- copy volume when measurable;
- throughput rows/sec.

## 32.5 Flamegraphs

Performance contribution guidelines should encourage:

```text
profile first
optimize second
```

Rust flamegraphs and Python profilers should be part of developer documentation.

---

# 33. Packaging and Distribution

## 33.1 Build system

Use:

```text
pyproject.toml
maturin
Cargo
uv
```

## 33.2 Python support

Recommended initial support:

```text
Python 3.11+
```

Before release, choose the exact supported upper range based on PyO3 and wheel testing.

Avoid supporting old Python versions merely for theoretical reach; the cost is substantial for a new performance-oriented library.

## 33.3 Wheels

Publish prebuilt wheels for mainstream:

- Linux x86_64;
- Linux aarch64;
- macOS arm64;
- macOS x86_64 if demand justifies it;
- Windows x86_64.

Avoid requiring normal users to install Rust.

## 33.4 ABI strategy

PyO3 `abi3` can reduce wheel matrix size when compatible with required features.

Use it only after confirming it does not constrain desired Python/Arrow integration.

## 33.5 Release flow

```text
PR
 ↓
tests
 ↓
statistical reference suite
 ↓
bench regression check
 ↓
wheel build test
 ↓
merge
 ↓
tag
 ↓
PyPI + GitHub release
```

---

# 34. Documentation

Documentation is part of the research product.

## 34.1 Four documentation layers

### Tutorials

"Get from signal to audit in 10 minutes."

### How-to guides

- purged CV;
- factor decay;
- cost stress;
- point-in-time joins.

### Reference

Every function, parameter and result field.

### Methodology

Explain:

- formulas;
- assumptions;
- failure modes;
- citations;
- when not to use the method.

## 34.2 Methodology pages are essential

A user should never see:

```text
DSR = 0.71
```

without being able to click through to:

- what DSR means;
- how it was calculated;
- assumptions;
- input trials;
- implementation notes;
- references.

---

# 35. Security and Trust Boundaries

Lacuna is analytical software, but still has security concerns.

## 35.1 Untrusted serialized Python

Never use pickle as the default report/cache interchange format.

## 35.2 Arrow FFI

Arrow's C Data Interface involves native memory pointers.

Only accept in-process Arrow C data from trusted producers.

For external files, use validated file-format readers rather than arbitrary pointer capsules.

## 35.3 Plugin execution

Plugins execute code.

Do not automatically install or execute plugins from report files.

## 35.4 Report HTML

Escape user-supplied labels/metadata before HTML rendering.

---

# 36. Licensing and Governance

## 36.1 License decision

Lacuna uses the **MIT License** only.

This keeps use, modification, redistribution, and commercial adoption straightforward across the
Python and Rust packages. Repository metadata, contribution terms, and every future distribution
must identify MIT as the sole project license and include the MIT license text.

Releases published before this decision retain the license grants under which they were originally
distributed. Changing the license on later versions does not revoke those existing grants.

## 36.2 Governance

Early project:

- maintainer-led;
- RFC required for major architecture changes;
- transparent roadmap;
- semantic versioning.

Later:

- technical steering group if community size warrants.

## 36.3 API stability

Pre-1.0:

- rapid evolution allowed;
- deprecation warnings where practical.

1.0:

- public API compatibility policy;
- serialized audit schema versioning;
- explicit statistical-method versioning.

---

# 37. Roadmap

## Phase 0 — Foundations

- repository;
- Python/Rust build;
- Arrow/Polars interchange;
- typed result model;
- test framework;
- benchmark framework;
- docs skeleton.

## Phase 1 — Signal diagnostics

- forward returns;
- IC;
- rank IC;
- quantiles;
- spreads;
- decay;
- turnover;
- basic report.

## Phase 2 — Validation

- IID/block/stationary bootstrap;
- permutation;
- walk-forward;
- purged CV;
- embargo;
- PSR;
- DSR.

## Phase 3 — Audit

- findings framework;
- structured audit;
- robustness rules;
- Markdown/HTML output;
- reproducibility metadata.

## Phase 4 — Robustness

- parameter surfaces;
- universe perturbation;
- regime analysis;
- subperiod analysis;
- experiment registry;
- multiple-testing corrections.

## Phase 5 — Trading realism

- cost models;
- stress surfaces;
- capacity;
- liquidity diagnostics;
- borrow-cost support.

## Phase 6 — Data correctness

- point-in-time helpers;
- availability-time joins;
- revision support;
- survivorship diagnostics;
- dataset validation.

## Phase 7 — Advanced inference

- CPCV;
- PBO;
- White Reality Check;
- Hansen SPA;
- advanced resampling.

## Phase 8 — Extensions

- options package;
- ML adapter;
- vendor schemas;
- backtester adapters.

---

# 38. v0.1 Scope

Do not try to ship the entire vision.

A compelling v0.1 should do one thing exceptionally well:

> **Turn a cross-sectional signal into a rigorous diagnostics report.**

## v0.1 required

### Inputs

- Polars;
- pandas;
- NumPy.

### Labels

- forward return construction.

### Signal analytics

- Pearson IC;
- Spearman IC;
- IC time series;
- quantile returns;
- top-bottom spread;
- monotonicity;
- turnover;
- decay.

### Validation

- basic block bootstrap;
- walk-forward;
- simple purged splitter.

### Reporting

- structured result objects;
- Markdown report;
- optional basic HTML.

### Native core

At least:

- grouped rank IC;
- bootstrap;
- interval purge.

### Quality

- property tests;
- statistical reference tests;
- performance benchmark suite;
- complete methodology docs.

## v0.1 explicitly excluded

- live trading;
- full portfolio backtester;
- SVI;
- ML training;
- distributed execution;
- GPU kernels;
- complicated market-impact simulation;
- plugin marketplace.

---

# 39. v1.0 Definition

Lacuna deserves 1.0 when it has:

- stable data-contract semantics;
- stable result schema;
- mature signal diagnostics;
- mature financial CV;
- robust bootstrap/permutation tools;
- PSR/DSR;
- multiple-testing support;
- parameter stability;
- regime analysis;
- cost stress;
- point-in-time checks;
- standardized audit;
- reproducible reports;
- strong Polars/pandas/Arrow interoperability;
- published benchmark suite;
- cross-platform wheels;
- comprehensive methodology documentation;
- real users applying it to independent research stacks.

---

# 40. Example End-to-End Workflow

```python
import polars as pl
import lacuna as lc

prices = pl.scan_parquet("data/prices/*.parquet")
factors = pl.scan_parquet("data/factors/*.parquet")

signal = (
    factors
    .select(
        "date",
        "instrument",
        pl.col("momentum_12_1").alias("signal"),
        "sector",
    )
)

study = lc.SignalStudy(
    signal=signal,
    prices=prices,
    time="date",
    instrument="instrument",
)

# Build labels using explicit execution assumptions.
study.set_forward_returns(
    horizons=["1D", "5D", "20D"],
    signal_time="close",
    entry="next_open",
    exit="close",
)

# Basic signal evidence.
ic = study.ic(method="spearman")
quantiles = study.quantiles(10)
decay = study.decay()
turnover = study.turnover()

# Cross-validation.
cv = lc.cv.PurgedWalkForward(
    train="5Y",
    test="1Y",
    step="6M",
    embargo="5D",
)

validation = study.validate(cv=cv)

# Robustness.
robustness = study.robustness(
    subperiods=True,
    regimes={
        "high_vol": high_vol_mask,
        "low_vol": low_vol_mask,
    },
)

# Produce the audit.
audit = study.audit(
    validation=validation,
    robustness=robustness,
)

print(audit.summary())
audit.to_markdown("lacuna-report.md")
audit.to_html("lacuna-report.html")
```

Potential summary:

```text
LACUNA SIGNAL AUDIT
──────────────────────────────────────────────

Signal                     momentum_12_1
Observations                9,421,884
Instruments                 6,182
Period                      2002-01-03 → 2026-07-31

EFFICACY
Mean 5D rank IC             0.031
IC t-stat                   4.12
Positive IC months          63.1%
Q10-Q1 spread               4.8% annualized
Quantile monotonicity       0.91

ROBUSTNESS
Subperiod stability         PASS
Regime stability            WARN
Parameter stability         NOT PROVIDED

VALIDATION
Purged walk-forward         PASS
Block-bootstrap CI          PASS
Multiple-testing            UNKNOWN

DATA QUALITY
Temporal leakage            PASS
Survivorship                UNKNOWN

──────────────────────────────────────────────
Finding:
The signal exhibits statistically persistent
cross-sectional information, but evidence is
concentrated in low-volatility regimes and
survivorship handling was not supplied.
```

---

# 41. Key Architectural Decisions

## ADR-001 — Python public API

**Decision:** Python is the primary interface.

**Reason:** Best quant research ecosystem and lowest adoption barrier.

## ADR-002 — Rust hot-path core

**Decision:** Performance-critical Lacuna-specific kernels use Rust.

**Reason:** Native performance, safety, concurrency and strong Python packaging.

## ADR-003 — Arrow as interoperability contract

**Decision:** Arrow-compatible columnar memory is the primary native data contract.

**Reason:** Avoid proprietary dataframe and reduce copies.

## ADR-004 — Polars preferred dataframe

**Decision:** Optimize first for Polars, while accepting pandas and NumPy.

**Reason:** Rust-native columnar/lazy architecture and strong fit for large panel data.

## ADR-005 — No backtester

**Decision:** Lacuna does not become a full event-driven trading engine.

**Reason:** Crowded space and dilutes core identity.

## ADR-006 — Structured result before visualization

**Decision:** Every analysis returns structured, serializable results.

**Reason:** Reports remain reproducible and machine-readable.

## ADR-007 — No implicit PASS for unknown evidence

**Decision:** Missing evidence is `UNKNOWN`.

**Reason:** Prevent misleading audits.

## ADR-008 — Performance regression is testable

**Decision:** Stable benchmark cases are maintained alongside correctness tests.

**Reason:** Performance is part of the public value proposition.

## ADR-009 — GPU is not v0.1

**Decision:** Optimize CPU architecture before adding GPU execution.

**Reason:** Most initial algorithms are memory/grouping/resampling dominated and GPU support adds substantial complexity.

GPU support should be evaluated later using actual workload benchmarks.

## ADR-010 — Optional query engines

**Decision:** DuckDB and DataFusion are adapters, not mandatory core dependencies.

**Reason:** Keep Lacuna lean and embeddable.

---

# 42. Success Criteria

Lacuna is succeeding if users say:

> "I run Lacuna before I trust a backtest."

rather than:

> "Lacuna is another backtester."

## Technical success

- native kernels meaningfully outperform naïve Python equivalents;
- large datasets do not require pandas materialization;
- no routine per-row Python loops;
- memory copies are understood;
- performance regressions are detected in CI;
- statistical outputs match reference implementations.

## Product success

- useful with one function call;
- useful without changing backtesting engine;
- findings are interpretable;
- unknown evidence is explicit;
- methodology is transparent.

## Ecosystem success

- adapters written by community;
- research papers cite Lacuna;
- strategy repositories include Lacuna audit output;
- backtesting frameworks integrate Lacuna diagnostics;
- independent users reproduce each other's audit results.

---

# 43. Technology Reference Notes

The architecture above is based on characteristics of the current ecosystem as of August 2026.

## Apache Arrow

Arrow defines a language-independent columnar in-memory format designed for analytical access, vectorization and cross-system interchange. Its C Data and C Stream interfaces enable in-process interchange between implementations.

Relevant documentation:

- Apache Arrow Columnar Format
- Apache Arrow C Data Interface
- Apache Arrow C Stream Interface

## Polars

Polars provides a Rust-based dataframe engine with lazy query optimization and streaming execution. Its current Python Lazy API can run queries in streaming mode, and GPU execution exists as an optional Open Beta backend through RAPIDS cuDF.

Lacuna should depend on the stable CPU path and treat GPU support as optional/future.

Relevant documentation:

- Polars Lazy API
- Polars Streaming
- Polars GPU Support

## PyO3

PyO3 provides Rust bindings to the Python interpreter and supports building native Python modules.

Relevant documentation:

- PyO3 User Guide
- PyO3 Building and Distribution

## maturin

maturin packages Rust/PyO3 extensions as Python wheels and supports mixed Python/Rust package layouts.

Relevant documentation:

- maturin User Guide
- maturin Configuration

## DataFusion

Apache DataFusion is an extensible Rust query engine built around Arrow. It is a plausible future execution/query integration for Lacuna but is unnecessary as a core dependency in the initial architecture.

## Rayon

Rayon provides work-stealing CPU parallelism and parallel iterators in Rust.

## Criterion.rs

Criterion.rs provides statistics-driven Rust microbenchmarking and is suitable for identifying performance improvements and regressions in native Lacuna kernels.

## uv and Ruff

`uv` is well suited to reproducible Python development through `pyproject.toml` and a cross-platform lockfile. Ruff provides fast Python linting and formatting.

---

# Final Positioning

**Lacuna is an open-source quantitative research validation library.**

It does not tell a trader what to buy.

It tells a researcher whether the evidence behind a trading idea survives serious scrutiny.

Its core promise is:

> **Bring a signal or backtest. Lacuna will try to find the gaps in the evidence.**

The architecture should reflect the same philosophy:

- Python where flexibility matters;
- Rust where speed matters;
- Arrow where interoperability matters;
- Polars where columnar analysis matters;
- mature scientific libraries where correctness matters;
- explicit assumptions everywhere.

The desired long-term reputation is simple:

> **If a strategy survives Lacuna, it has earned the right to be tested with real money.**
