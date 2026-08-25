# Adapters, execution, and plugins

**Status:** Arrow/Polars/pandas ingestion and conservative local execution are part of the v0.1 boundary. DuckDB, DataFusion, backtester integrations, and third-party plugins are later and must follow the contracts here.

These systems control how Lacuna touches external data and code. Their shared design goal is a small, explicit trust and materialization boundary.

## Adapter boundary

Adapters translate an external representation into Lacuna's semantic data contracts. They may:

- discover columns and physical dtypes;
- normalize supported tabular containers;
- preserve or expose laziness;
- attach source metadata and capabilities;
- provide a stable row or instrument identity when the source has one.

They must not:

- infer decision-time semantics without configuration;
- perform hidden joins, imputation, winsorization, or sorting;
- run statistical analyses;
- discard unsupported rows silently;
- retain mutable references after validation unless the API explicitly documents borrowing.

The detailed conversion and copy policy lives in [The data boundary](../development/data-boundary.md).

## Capability-based protocols

Prefer narrow capabilities to framework-specific base classes:

- `TabularSource`: schema, scan/collect, partition metadata;
- `PriceSource`: price fields, currency, adjustment semantics, availability policy;
- `UniverseSource`: point-in-time membership intervals;
- `ExperimentStore`: append/query attempts and artifact manifests;
- `BacktestSource`: trades, returns, positions, and execution assumptions.

An adapter declares capabilities and limitations. Callers validate required capabilities before reading large data.

## Execution planner

The planner chooses an implementation; it does not change methodology. Its input includes:

- operation and method version;
- row/column counts when cheaply known;
- dtype, null, chunk, and sort characteristics;
- source capabilities and whether collection is required;
- configured memory and thread budgets;
- available Python/native/database backends;
- deterministic-mode requirements.

The plan records:

- selected backend and reason;
- materialization and copy points;
- expected temporary memory;
- partitioning/chunking strategy;
- thread allocation;
- fallbacks and any semantic limitations.

If no implementation satisfies the contract, fail before expensive execution with a useful message.

### Conservative dispatch

| Situation | Default |
| --- | --- |
| small input or unsupported dtype | Python/vectorized reference |
| large supported Arrow-compatible input | Rust native kernel |
| lazy scan with pushdown-safe operations | preserve lazy execution |
| workload already in DuckDB/DataFusion | future query-engine adapter |
| unknown row count or tight memory budget | bounded streaming/chunked plan |

Thresholds are benchmark-derived configuration, not public statistical parameters. Record them in provenance when they influence backend selection.

## Thread and memory budgets

Lacuna owns a single top-level thread budget. Native kernels, BLAS, Polars, and query engines must not each create the full machine-sized pool. Nested parallel work defaults to sequential unless the planner assigns a sub-budget.

Memory estimates include inputs that must be copied, output buffers, sort indices, bootstrap state, and peak temporary arrays. A plan that exceeds the configured budget should stream, spill through an explicit future backend, or fail before allocation. It must not rely on the operating system to terminate the process.

## Optional query engines

DuckDB and DataFusion adapters are optional acceleration/integration layers. Pushdown is permitted only when equivalent semantics are established for:

- null and NaN handling;
- timezone and timestamp precision;
- stable ordering and tie behavior;
- numeric aggregation and overflow;
- categorical/dictionary values;
- window boundaries.

Generated SQL or logical plans should be inspectable. Never interpolate untrusted identifiers or values into SQL; use identifier validation and parameter binding.

## Backtester adapters

Backtester integrations translate artifacts, not methodology. A valid adapter states:

- whether returns are gross or net;
- return frequency and compounding convention;
- position timing and execution delay;
- price field and adjustment policy;
- cost/borrow assumptions;
- timezone, calendar, and session rules;
- treatment of missing/delisted instruments.

The adapter should reject ambiguous payloads. Framework defaults must be serialized into provenance rather than treated as implicit knowledge.

## Plugin model

Plugins may eventually contribute adapters, audit rules, cost models, report sections, or method implementations. Entry-point groups must be domain-specific and versioned. A plugin descriptor includes:

- plugin ID, distribution, and version;
- provided capability names and protocol versions;
- configuration schema;
- method/rule versions;
- required optional dependencies.

Discovery returns metadata only. Execution requires explicit activation through configuration or API. Conflicting capability names are errors unless the caller chooses one.

Python plugins are trusted code running with the user's process permissions. Lacuna must not describe them as isolated. Reports identify every activated plugin.

### Compatibility

Protocol compatibility is negotiated independently of package version. Unknown major protocol versions are rejected. Minor additions are allowed only when existing required behavior is unchanged.

A plugin-provided statistical method must meet the same reference, validation, versioning, and reporting requirements as a built-in method.

## CLI boundary

The CLI is a thin adapter over public Python services. It may load configuration, resolve paths, configure logging, and select output renderers. It must not contain unique analysis logic.

CLI behavior should define:

- stable exit-code categories;
- machine-readable output mode;
- stdout for requested results and stderr for diagnostics;
- `--no-color` and non-interactive operation;
- dry-run/explain-plan support before expensive work;
- safe overwrite behavior for artifacts.

The implemented v0.1 command is a thin file adapter around `SignalStudy`:

```bash
lacuna signal \
  --signal factor.parquet \
  --prices prices.parquet \
  --horizon 5D \
  --price-adjustment total_return_adjusted \
  --quantiles 5 \
  --bootstrap-resamples 10000 \
  --seed 42 \
  --format html \
  --out factor-audit.html
```

Parquet, CSV, Arrow IPC, and Feather inputs are scanned lazily before the public services apply
their explicit materialization boundary. Requested results go to stdout; file-write diagnostics and
errors go to stderr. Existing artifacts are not replaced without `--overwrite`. Exit code `0` means
execution completed under the requested finding policy, `1` means execution failed, and `3` means
`--fail-on fail` or `--fail-on warn` matched an audit finding. `--format json` emits JSON without
progress or color sequences. `--no-color` is accepted and terminal output is currently plain text.

`lacuna doctor [--json]` remains available for build and native-extension diagnostics. Audit of
standalone return/trade artifacts, dataset checks, dry-run planning, and developer benchmarks are
separate later CLI stages.

## Observability

Structured execution events may report phases, row counts, durations, allocations, and selected backend. They must not log sample data, credentials, or proprietary query text by default. Progress callbacks are optional and cannot affect calculation results.

## Required tests

- capability negotiation rejects missing or incompatible features before collection;
- eager, lazy, chunked, and native paths agree within declared tolerance;
- planner decisions are deterministic for the same capabilities/configuration;
- thread budget is not multiplied by nested backends;
- low-memory plans avoid unbounded collection;
- SQL identifiers/values cannot inject statements;
- backtester fixtures expose gross/net and timing mismatches;
- plugin discovery has no import-time analytical side effects;
- plugins never execute without explicit activation;
- incompatible protocol majors and name conflicts fail clearly;
- CLI machine output contains no progress or color escape sequences.
