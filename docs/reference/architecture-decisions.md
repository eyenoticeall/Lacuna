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
| ADR-014 | Cross-phase audits use categorical coverage | Unlike evidence remains visible without one misleading universal score |
| ADR-015 | Diagnostic portfolio projections are not a backtester | Explicit cohort weights remain outside portfolio state and execution simulation |
| ADR-016 | PyPI identity differs from Python import identity | Users install `lacuna-quant`; code continues to import `lacuna` |
| ADR-017 | Native performance work is admission-gated | v0.14 preserves Python semantics, stable ABI wheels, and reference fallbacks |

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

## ADR-014 — Cross-phase audits use categorical coverage, not one universal score

**Context:** signal efficacy, temporal leakage, selection-aware inference, parameter stability,
execution costs, adapter declarations, and extension evidence answer unlike questions. Assigning
one weight system across all scopes would make omitted or inapplicable evidence easy to hide and
would imply comparability that the methods do not establish.

**Decision:** standardized audits select a versioned scope profile and expose capability/category
coverage. Each capability is required, optional, or not applicable. Coverage conclusions remain
separate from source findings, which are propagated without state, severity, threshold, category,
or evidence reinterpretation. The standardized profile has no universal score model.

**Consequences:**

- users can see exactly which released method families count for each capability;
- missing required evidence is `UNKNOWN`, not zero credit hidden inside one number;
- source-method upgrades retain their own independent method/finding versions;
- custom organizational profiles must be explicitly identified and versioned;
- profile matching fails when a method maps ambiguously, and unrecognized evidence remains visible;
- the original v0.1 signal score remains available only within its frozen narrow contract.

**Revisit when:** an empirically validated decision model exists for one narrowly declared use case.
It must remain optional, publish its estimand/weights/calibration, show coverage separately, and
must not replace categorical evidence or source findings.

## ADR-015 — Diagnostic portfolio projections are not a backtester

**Status:** accepted on 2026-08-26.

**Context:** signal researchers need inspectable long/short weights, cohort returns, exposure
reconciliation, concentration, and implied target-weight turnover. Hiding those calculations behind
quantile-return plots makes weighting assumptions difficult to review. Conversely, compounding
cohorts, resolving overlapping holdings, carrying cash, or simulating fills would reverse ADR-005
and duplicate execution engines.

**Decision:** Lacuna may construct an immutable one-horizon diagnostic portfolio projection only
from an explicit `SignalTransformResult` produced by `bucketize()`. The projection owns target
weights and arithmetic forward-return contributions for independent observation cohorts. It does
not own a portfolio state machine or execution model.

**Consequences:**

- callers choose long/short buckets, horizon, weighting, gross/net exposure, and group policy;
- a market-neutral gross-one projection allocates `+0.5` long and `-0.5` short, not 200% gross;
- weights, exposure reconciliation, cohort contributions, coverage, concentration, turnover, and
  attrition are stored as evidence;
- returns are not compounded and overlapping cohorts are not consolidated;
- cash, financing, borrow, orders, fills, execution timing, costs, capacity, and realized holdings
  are neither inferred nor simulated;
- explicit projection weights can be passed to Lacuna cost/capacity methods or an external
  backtester, preserving dependency direction;
- the public type name includes `Projection` rather than `Portfolio` or `Backtest` alone to avoid a
  stronger behavioral claim.

**Rejected alternatives:** adding a cumulative-return helper would introduce an implicit overlap
and cash policy; accepting raw signals would silently choose buckets; treating each leg as unit
exposure would make the nominal gross setting misleading.

**Validation:** exact gross/net/leg reconciliation, permutation invariance, one-sided group policy,
contribution identities, temporal label alignment, and an explicit regression for the 200%-gross
interpretation error are release gates.

**Revisit when:** a separately scoped backtesting package is proposed with explicit state,
execution, accounting, and cost contracts. It must consume Lacuna evidence without moving those
responsibilities into `lacuna.signal`.

## ADR-016 — PyPI identity differs from Python import identity

**Status:** accepted on 2026-08-27.

**Context:** the PyPI project `lacuna` is active and unrelated to this repository. Reusing that
name would misdirect users and extension dependency resolution, while renaming the established
Python package would create broad migration cost without improving analytical clarity.

**Decision:** publish core as the distribution `lacuna-quant` while preserving the Python import
package and CLI as `lacuna`. Publish the optional extension as `lacuna-options`; from extension
`0.2.0`, its dependency is `lacuna-quant>=0.13,<0.14`. Registry publication uses PyPI Trusted
Publishing from the tag-only `release.yml` workflow and protected GitHub environments. Core uses
`pypi`; the extension uses `pypi-options` because PyPI requires distinct pending-publisher identity
tuples for separate project names.

**Consequences:**

- package installers, metadata diagnostics, release archives, and dependency bounds use
  `lacuna-quant`, while user code continues to use `import lacuna`;
- this repository never uploads to, depends on, or presents the unrelated PyPI `lacuna` project as
  Lacuna;
- old GitHub wheels distributed as `lacuna` must be uninstalled before migration because two
  distributions cannot safely own the same import path;
- installation diagnostics fail when both distribution identities are present;
- only the already verified GitHub release distributions reach PyPI, core publishes before the
  dependent extension, and a clean registry-only install is release-blocking;
- no long-lived PyPI token is stored, and publish jobs receive only read access plus OIDC identity.

**Rejected alternatives:** requesting transfer of an active unrelated project does not satisfy
PyPI name-conflict policy; renaming the Python import would break every caller for a packaging-only
concern; storing an API token would add a durable credential where OIDC is available; a shim named
`lacuna` would collide with and misrepresent the unrelated project.

**Validation:** release source verification fixes the two distribution identities, archive
verification fixes normalized filenames and metadata names, options metadata fixes the compatible
core bound, clean-wheel tests preserve import/native/CLI identity, and post-publication smoke
installs both exact versions from PyPI.

**Revisit when:** PyPI deprecates Trusted Publishing or the project intentionally undertakes a
major-version import rename. Any replacement must preserve an explicit migration and collision
policy.

## ADR-017 — Native performance work is admission-gated

**Status:** accepted on 2026-08-27.

**Context:** Lacuna 0.13 already contains three small Rust analytical kernels, but their Python
boundary converts through owned sequences and several larger public operations still perform
observation-, scenario-, fold-, or resample-scaled Python work. Moving every plausible loop to Rust
would duplicate mature Polars/NumPy behavior, risk temporal and statistical contracts, and increase
wheel complexity without proving an end-to-end benefit.

**Decision:** v0.14 treats Rust migration as an evidence program rather than a Rust quota. Every
candidate is compared with an already optimized Python, NumPy, or Polars reference and ships
natively only after transfer-inclusive correctness, latency, and memory gates pass on the same
runner. Python remains authoritative for methodology, validation, random-stream identity,
configuration, provenance, findings, errors, and public result construction.

The v0.14 native boundary preserves `abi3-py311`, copies normalized typed input into Rust-owned
memory before releasing the interpreter lock, and remains single-threaded. Internal contiguous
carriers are permitted, but public v0.13 result types, AnalysisResult schema 1, method versions,
canonicalization v1, and deterministic NumPy-generated random streams remain unchanged.

**Consequences:**

- each candidate retains a callable reference implementation and terminal evidence decision;
- algorithmic and Polars improvements precede native design and can be the final implementation;
- missing native modules may use the existing documented fallback, but native contract failures
  are never swallowed and recomputed silently;
- a typed-buffer dependency must pass MSRV, license, stable-ABI, wheel-size, and Python 3.11–3.14
  same-wheel tests before dependent kernels proceed;
- v0.14 adds no Rayon pool, native RNG, public carrier redesign, or canonicalization-v2 identity;
- Arrow C Data/C Stream borrowing is deferred to a separate lifetime, unsafe-code, null-bitmap,
  chunking, release-callback, and packaging review;
- a milestone can succeed with no new native kernel when no candidate passes admission.

**Rejected alternatives:** migrating the largest-looking Python loops before optimizing their
algorithms would measure an avoidably weak baseline; dropping `abi3` would trade user portability
for an internal optimization; borrowing mutable Python buffers while detached would weaken memory
safety; native RNG would change established streams or method identities; public compact carriers
would combine performance work with an unrelated compatibility migration.

**Validation:** a versioned migration benchmark records effective shape, all timed repetitions,
process RSS, copy and workspace bytes, thread configuration, output checksum, exact commit, and
admission outcome. Shipped paths need Rust unit/property tests, Python binding tests, differential
and adversarial fixtures, same-wheel Python 3.11–3.14 proof, target-wheel smoke, reproduced nightly
and release-preflight evidence, and no unexplained legacy regression above 15%.

**Revisit when:** a separately benchmarked proposal establishes coordinated native parallelism,
safe Arrow ownership, a new versioned random stream, or a public carrier/canonicalization migration.
Each requires its own compatibility and release design rather than an exception to this decision.

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
