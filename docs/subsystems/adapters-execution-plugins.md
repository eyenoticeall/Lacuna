# Adapters, execution, and plugins

**Status:** Arrow/Polars/pandas ingestion and conservative local execution are implemented. The
v0.6 milestone adds a DuckDB Arrow-stream adapter, a scikit-learn CV bridge, declarative vendor and
backtest artifact schemas, and metadata-only plugin discovery with explicit trusted activation.
DataFusion, framework-specific adapters, and a plugin marketplace remain later.

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

## Implemented adapter result

Every new boundary returns `AdaptedFrame(frame, evidence)`. `frame` is a Polars eager or lazy frame;
`columns` inspects its schema without collecting, and `lazy` exposes the physical state. Evidence is
an immutable `AnalysisResult` containing the source type, schema/mapping identity, materialization
state, adapter assumptions, column counts, and eager row count when known.

Mapping APIs take `canonical -> source`, not the inverse. They reject empty names, duplicate source
targets, missing required canonical fields, and renames that would overwrite an unrelated existing
canonical column. They preserve row order and extra columns. Normalization is not authorization to
sort, impute, join, aggregate, deduplicate, or reinterpret identifiers.

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

## DuckDB Arrow-stream adapter

`lacuna.adapters.from_duckdb(source, *, batch_size=100_000, required=(), collect=True)` consumes an
already executed trusted DuckDB connection or relation. It calls DuckDB's current
`to_arrow_reader(batch_size)` API and records the explicit legacy `fetch_record_batch` compatibility
path when encountered. The adapter never accepts or creates SQL, so query construction and safe
parameter binding remain with the caller.

The stream enters Polars through the ordinary Arrow boundary; pandas is never an intermediate.
`batch_size` is a positive integer, `required` names unique non-empty fields, and the result evidence
records the reader method, batch size, materialization state, copy classification, columns, and row
count when eager. DuckDB itself is neither imported nor required at core import time.

See DuckDB's [Python conversion API](https://duckdb.org/docs/stable/clients/python/conversion.html#export-to-arrow)
for the producer contract. A future pushdown adapter—not this conversion function—may accept an
inspectable query plan after equivalence is established for:

- null and NaN handling;
- timezone and timestamp precision;
- stable ordering and tie behavior;
- numeric aggregation and overflow;
- categorical/dictionary values;
- window boundaries.

Generated SQL or logical plans should be inspectable. Never interpolate untrusted identifiers or values into SQL; use identifier validation and parameter binding.

DataFusion remains a later optional adapter under the same requirements.

## scikit-learn temporal CV bridge

`lacuna.adapters.as_sklearn_cv(splitter, interval_data, ...)` precomputes a Lacuna `WalkForward`,
`PurgedKFold`, or `CombinatorialPurgedKFold` result and exposes scikit-learn's `split` and
`get_n_splits` protocol. Precomputation freezes row ordering and interval evidence before estimator
evaluation. Each `split` call yields fresh `int64` train/test arrays.

The bridge deliberately imports no scikit-learn package. It validates the optional `X` and `y` row
counts against the precomputed interval table. `groups` is rejected because silently reinterpreting
it would conflict with Lacuna's explicit time/interval contract; encode grouping in the input table
or use a different reviewed splitter. The original Lacuna evidence remains accessible as
`SklearnCV.evidence`.

This shape follows scikit-learn's documented
[cross-validation iterator contract](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators),
but temporal leakage guarantees still come from the selected Lacuna splitter and its interval data.

## Vendor schemas

`VendorSchema` is a versioned, immutable declaration for one external dataset revision. It records:

- a stable `schema_id` and positive `schema_version`;
- canonical-to-source columns and required canonical fields;
- availability as `point_in_time`, `latest_only`, or `unknown`;
- revisions as `versioned`, `latest_only`, `not_applicable`, or `unknown`;
- optional timezone plus the mapped timestamp columns that must carry it;
- price-adjustment and identifier policies as explicit source semantics.

Point-in-time declarations must map `available_time`; versioned declarations must map
`revision_time` or `revision_id`. `adapt_vendor(..., collect=False)` preserves laziness by default,
validates physical timezone metadata without collection, freezes the caller's mapping against later
mutation, and returns the mapping and every declared semantic in evidence. It does not prove the
vendor's claim or turn `unknown`/`latest_only` into point-in-time safety.

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

The implemented generic boundary is `BacktestSchema` plus `BacktestSemantics`. It supports
`returns`, `trades`, and `positions` artifacts with minimum canonical fields:

| Artifact | Required canonical fields |
| --- | --- |
| returns | `time`, `strategy`, `return` |
| trades | `decision_time`, `execution_time`, `instrument`, `quantity`, `price` |
| positions | `time`, `instrument`, `position` |

Every `BacktestSemantics` field is required. `returns` is exactly `gross` or `net`; compounding is
`simple` or `log`; cost and borrow inclusion are explicit. `adapt_backtest(..., collect=False)` maps
the artifact without calculating a return, trade, cost, or position and records
`methodology_executed=False`. Framework-specific helpers should be added only when maintained demand
justifies a versioned schema and fixtures; CSV/Parquet plus this generic mapping remains the stable
fallback.

## Plugin model

Plugins may contribute adapters, audit rules, cost models, report sections, or method implementations.
The implemented entry-point groups are domain-specific and protocol-major-versioned:

| Capability | Entry-point group |
| --- | --- |
| adapters | `lacuna.adapters.v1` |
| audit rules | `lacuna.audit_rules.v1` |
| cost models | `lacuna.cost_models.v1` |
| methods | `lacuna.methods.v1` |
| report sections | `lacuna.report_sections.v1` |

These names follow the [PyPA entry-points specification](https://packaging.python.org/en/latest/specifications/entry-points/)
and use project-prefixed groups to avoid ecosystem collisions. A plugin descriptor includes:

- plugin ID, distribution, and version;
- provided capability names and protocol versions;
- configuration schema;
- method/rule versions;
- required optional dependencies.

`discover_plugins(group=...)` reads installed distribution metadata only. It returns a deterministic
tuple of `PluginCandidate` values and does not call `EntryPoint.load()`. `select_plugin(...)` rejects
missing names and ambiguous providers unless the caller supplies the distribution. This separation
is a security boundary in behavior, though not a sandbox.

`activate_plugin(candidate, ...)` is the only import/execute step. It first freezes JSON-compatible
configuration evidence, then loads a callable entry-point factory and passes that mapping. The
factory must return an object whose `.descriptor` is `PluginDescriptor`, whose `plugin_id` matches
the entry-point name, whose protocol major matches, and whose advertised capabilities contain any
requested capability. Import, factory, descriptor, compatibility, and capability failures become
`PluginError`.

Python plugins are trusted code running with the user's process permissions. Lacuna must not describe them as isolated. Reports identify every activated plugin.

Activation evidence records the distribution name/version, entry-point target, protocol,
capabilities, method versions, dependencies, resolved configuration, and
`trusted_in_process_code=True`. A report or bundle may record that evidence; it must never activate
a plugin merely because serialized content names one.

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

The v0.6 implementation covers the adapter/plugin subset with unit tests, real DuckDB and
scikit-learn interoperability tests, optional-dependency-free core imports, exact public export and
signature fixtures, and clean-wheel smoke tests. Planner, DataFusion, framework-specific, thread
budget, spill, and plugin-marketplace bullets remain acceptance gates for those later capabilities,
not claims about the v0.6 surface.
