# Architecture decisions

This page expands the decision summary in the technical specification into implementation guidance. All listed decisions are **accepted**. A decision is changed through an explicit replacement or superseding record, not by quietly violating it in code.

## Decision index

| ID | Decision | Principal consequence |
| --- | --- | --- |
| ADR-001 | Python is the public API | Python owns policy, orchestration, and user experience |
| ADR-002 | Rust handles Lacuna-specific hot paths | Native work requires evidence and a coarse stable boundary |
| ADR-003 | Arrow is the interoperability contract | Prefer columnar buffers over dataframe-specific internals |
| ADR-004 | Polars is the preferred dataframe | Optimize Polars first while accepting pandas and NumPy |
| ADR-005 | Lacuna is not a backtester | Consume backtest artifacts; do not build an event engine |
| ADR-006 | Structured results precede visualization | Reports are reproducible projections of evidence |
| ADR-007 | Missing evidence is unknown | Audits never turn absence into an implicit pass |
| ADR-008 | Performance regression is testable | Stable benchmarks accompany correctness tests |
| ADR-009 | GPU is outside v0.1 | Establish a strong CPU architecture before GPU complexity |
| ADR-010 | Query engines are optional adapters | Keep core lean, embeddable, and semantically controlled |
| ADR-011 | Extensions are independently versioned distributions | Optional domains evolve without coupling core SemVer or dependencies |
| ADR-012 | Plugin discovery never authorizes execution | Installed metadata is safe to enumerate; loading is an explicit trust decision |
| ADR-013 | Evidence bundles are deterministic data, never code | Portable reports are checksummed, bounded, and verified without extraction or execution |

## ADR-001 — Python public API

**Context:** quantitative researchers rely on Python's data, statistics, notebook, and orchestration ecosystem. A Rust-first public interface would raise adoption and extension costs.

**Decision:** Python is the primary user interface.

**Consequences:**

- public validation, configuration, result construction, audit orchestration, and errors are designed in Python;
- type hints and stable Python objects define compatibility;
- Rust is replaceable behind internal dispatch and cannot become the only definition of methodology;
- study objects and the CLI delegate to public Python services.

**Revisit when:** another language requires a first-class client. Prefer a language-neutral artifact/service boundary rather than leaking PyO3 details.

## ADR-002 — Rust hot-path core

**Context:** large panel, grouping, rolling, ranking, resampling, and overlap workloads can exceed practical pure-Python performance and memory behavior.

**Decision:** performance-critical Lacuna-specific kernels use Rust.

**Consequences:**

- optimization follows profiling and a correct reference;
- `lacuna-core` remains Python-independent and `lacuna-python` owns PyO3 conversion;
- calls are coarse-grained, typed, panic-safe, and tested differentially;
- interpreter-lock and shared thread-budget behavior are part of the contract;
- packaging must ship reliable native wheels.

**Revisit when:** an existing vectorized/query implementation meets the performance and semantic contract more simply. Rust is an option, not a quota.

## ADR-003 — Arrow interoperability contract

**Context:** dataframe ecosystems differ, but many can exchange typed columnar buffers through Arrow.

**Decision:** Arrow-compatible columnar memory is the primary native data contract.

**Consequences:**

- conversions target Arrow-compatible arrays/streams rather than proprietary dataframe objects;
- null bitmaps, offsets, chunking, dictionary values, timestamp metadata, and lifetimes require validation;
- zero-copy is preferred where safe but never promised unconditionally;
- import/export compatibility is tested across supported containers.

**Revisit when:** a major input class cannot express required semantics or a safer standard supersedes Arrow for the relevant boundary.

## ADR-004 — Polars preferred dataframe

**Context:** Lacuna's workloads are large, columnar, group-heavy, and benefit from lazy execution. Polars aligns with the Rust/Arrow architecture.

**Decision:** optimize first for Polars while accepting pandas and NumPy.

**Consequences:**

- examples and primary dataframe paths use Polars;
- APIs accept capabilities/semantic fields rather than expose Polars-only internals;
- pandas support is an optional adapter with documented copy/index behavior;
- NumPy remains suitable for dense numerical inputs;
- lazy operations stay lazy only when semantic equivalence is preserved.

**Revisit when:** usage and benchmark evidence show another dataframe deserves equal first-class optimization.

## ADR-005 — No backtester

**Context:** full event-driven execution engines require brokerage simulation, order lifecycle, portfolio accounting, and market microstructure scope that would dilute Lacuna's validation focus.

**Decision:** Lacuna does not become a full backtester.

**Consequences:**

- Lacuna consumes signals, returns, trades, positions, and assumptions from other systems;
- backtester adapters make timing, gross/net, cost, calendar, and delisting semantics explicit;
- Lacuna may construct forward labels and research diagnostics but does not own order routing or portfolio simulation;
- integrations remain translation layers, not forks of external engines.

**Revisit when:** never for convenience alone. A proposal must show that validation is impossible without narrowly scoped simulation and preserve the product boundary.

## ADR-006 — Structured result before visualization

**Context:** plots without source evidence are difficult to reproduce, review, serialize, or reuse in audits.

**Decision:** every analysis returns structured, serializable results before rendering.

**Consequences:**

- `AnalysisResult` carries metrics, typed tables, findings, provenance, warnings, and versions;
- plots and reports reference stored tables and rendering configuration;
- JSON is the canonical machine representation;
- renderers cannot change statistical conclusions.

**Revisit when:** a truly streaming visualization cannot retain full evidence. It must still emit a sufficient summarized/result artifact with declared information loss.

## ADR-007 — No implicit pass for unknown evidence

**Context:** audits can look reassuring when unavailable checks are omitted or default to success.

**Decision:** missing required evidence is `UNKNOWN`.

**Consequences:**

- applicability is explicit for every rule;
- `UNKNOWN` differs from `NOT_APPLICABLE` and from a confirmed failure;
- report summaries expose evidence coverage alongside scores;
- scoring has an explicit, versioned unknown policy;
- latest-only or ambiguous data cannot claim point-in-time safety.

**Revisit when:** the state vocabulary changes. The epistemic distinction between absent evidence and successful evidence must remain.

## ADR-008 — Performance regression is testable

**Context:** high performance is part of Lacuna's value, and accidental copies or dispatch changes can erase it without breaking correctness tests.

**Decision:** maintain stable benchmark cases alongside correctness tests.

**Consequences:**

- benchmarks cover Rust kernels and end-to-end Python boundaries;
- representative data scales, shapes, null density, grouping, and chunking are fixed and versioned;
- latency, throughput, peak memory, copies, and threads are measured;
- regressions are evaluated statistically, with roughly 10% as an investigation threshold rather than a single-run verdict;
- performance improvements still require correctness equivalence.

**Revisit when:** CI hardware/noise makes fixed thresholds unreliable. Improve normalization and sampling before dropping regression protection.

## ADR-009 — GPU is not v0.1

**Context:** initial workloads are primarily memory-, grouping-, rolling-, and resampling-bound. GPU execution adds packaging, transfer, determinism, precision, and optional-dependency complexity.

**Decision:** optimize the CPU architecture before adding GPU execution.

**Consequences:**

- no GPU runtime is required by core or v0.1;
- APIs must not be designed around a hypothetical device backend;
- CPU memory locality, streaming, vectorization, and parallelism receive priority;
- a future GPU proposal needs end-to-end workload evidence including transfer and reproducibility costs.

**Revisit when:** supported real workloads show a substantial, repeatable end-to-end benefit that CPU changes cannot reasonably deliver.

## ADR-010 — Optional query engines

**Context:** DuckDB and DataFusion can provide query pushdown and scale benefits, but mandatory engines would increase installation and semantic complexity.

**Decision:** DuckDB and DataFusion are optional adapters, not core dependencies.

**Consequences:**

- core remains usable without either engine;
- query plans are selected through capability-aware execution planning;
- pushdown requires verified equivalence for nulls, timezones, ordering, aggregation, and overflow;
- generated queries are inspectable and parameterized safely;
- unsupported semantics fall back or fail clearly rather than changing results.

**Revisit when:** an engine becomes required for a well-defined product tier. Core embeddability and an explicit compatibility boundary must still be preserved.

## ADR-011 — Independently versioned extensions

**Context:** options research and other specialist domains have heavier dependencies, different
release cadence, and model-specific contracts that should not enlarge or destabilize core.

**Decision:** optional domain extensions are separate distributions with independent versions,
dependency ranges, changelogs, API fixtures, tests, and build metadata.

**Consequences:**

- core never imports an extension and remains usable without it;
- an extension may depend inward on reviewed core data/evidence contracts;
- one GitHub Release may carry compatible core and extension artifacts without aligning versions;
- release verification and provenance cover each distribution independently and the joint install;
- a compatibility-range change is reviewed and documented like another public API decision.

**Revisit when:** a capability becomes foundational to nearly every core workflow and its dependency/
release risk is demonstrably acceptable. Migration must preserve old extension identities.

## ADR-012 — Explicit plugin trust transition

**Context:** Python entry points are useful discovery metadata, but loading a target imports and can
execute arbitrary code with the current process permissions.

**Decision:** discovery reads distribution metadata only. Selection resolves conflicts without
loading. Only an explicit activation API crosses into trusted in-process execution and records the
identity, protocol, capabilities, configuration, and dependency declarations.

**Consequences:**

- import-time and report-deserialization paths never activate plugins;
- entry-point groups are domain-specific and protocol-major-versioned;
- name conflicts, incompatible majors, and missing capabilities fail before use;
- activation evidence must not be described as sandboxing or isolation;
- safer future out-of-process execution can implement another activation backend without weakening
  the metadata boundary.

**Revisit when:** a process-isolated protocol is implemented and threat-modeled. Metadata-only
discovery and caller-visible authorization remain requirements.

## ADR-013 — Deterministic evidence bundles are data, never code

**Context:** a portable report must preserve enough identity and provenance for review without
turning archive deserialization into code execution, plugin activation, proprietary-data copying, or
an unbounded extraction surface. Internal checksums also must not be misrepresented as proof of
authorship.

**Decision:** `.lacuna` bundle v1 is a deterministic, stored ZIP of canonical JSON and escaped report
projections. A strict manifest declares every non-executable member, size, media type, role, and
SHA-256. Creation adds no source data automatically; verification extracts nothing and executes
nothing.

**Consequences:**

- the archive and manifest have independent published compatibility versions;
- canonical audit/evidence containing secrets, signed URLs, or machine paths fails closed rather
  than being silently rewritten;
- supplemental metadata is redacted with a value-free audit log;
- archive paths, types, permissions, sizes, encoding, membership, and digests are bounded and
  validated before success;
- v1 claims identifiable artifact integrity only, not recomputability, numerical reproduction,
  bitwise reproduction across executions, or authenticity;
- arbitrary files, pickle, source datasets, lockfiles, plugins, and executable content require a
  later separately threat-modeled contract rather than an escape hatch in v1.

**Revisit when:** a reproducer can securely obtain declared inputs, construct an environment,
execute a versioned invocation, and compare results under a documented tolerance. Preserve the
non-executing verifier and explicit authenticity boundary.

## Recording future decisions

Add a new decision when a change is hard to reverse, affects several packages, changes a trust boundary, or alters public methodology/compatibility. Include:

- sequential ID and concise title;
- status and date;
- context and constraints;
- decision and considered alternatives;
- positive and negative consequences;
- migration and validation requirements;
- concrete revisit triggers;
- links to superseded decisions.

Method parameter choices normally belong in methodology documentation and method versions, not architecture decisions. Use an ADR when the choice changes ownership, dependency direction, platform strategy, or a cross-cutting invariant.
