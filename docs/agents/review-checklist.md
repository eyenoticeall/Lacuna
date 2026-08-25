# Review checklist

Review Lacuna changes in risk order. A clean style check cannot compensate for temporal leakage, a wrong estimator, or irreproducible selection.

## 1. Scope and architecture

- [ ] The change matches the requested scope and current roadmap status.
- [ ] Public orchestration remains in Python and compute kernels remain policy-free.
- [ ] Adapters, analysis, audit, reporting, storage, and CLI responsibilities are separated.
- [ ] Optional features do not become core import-time dependencies.
- [ ] Public names and exports are deliberate; internal details remain private.
- [ ] New abstraction or dependency has more than speculative value.

## 2. Temporal and identity correctness

- [ ] Availability is distinguished from event/effective/observation time.
- [ ] Every historical join proves `available_time <= decision_time`.
- [ ] Labels, folds, embargoes, and memberships use documented half-open intervals.
- [ ] Stable instrument identity is used instead of ticker-only matching.
- [ ] Revisions, duplicates, sort order, calendars, timezones, and session cutoffs are explicit.
- [ ] Survivorship and latest-revision limitations produce findings or unknown states.
- [ ] Tests contain future, boundary, and delisted cases where applicable.

## 3. Statistical validity

- [ ] The estimand, method, assumptions, and sample eligibility are stated.
- [ ] Missing values, NaN/infinity, ties, weights, and degrees of freedom have policies.
- [ ] Small, empty, constant, and degenerate samples have defined outcomes.
- [ ] Dependence-aware methods are used when observations are not IID.
- [ ] Multiple testing uses the complete declared candidate family.
- [ ] CPCV model-fitting paths are not conflated with CSCV/PBO selection analysis.
- [ ] Strategy-family tests declare one benchmark and whether positive or negative is better.
- [ ] Dependent matrix resampling shares indices across strategies and records block assumptions.
- [ ] Selection ties, partition sensitivity, studentization, and null recentering are inspectable.
- [ ] Randomized methods have deterministic, schedule-independent substreams.
- [ ] Evidence comes from an independent oracle, analytical fixture, or controlled simulation.
- [ ] Reported precision and certainty do not exceed supporting evidence.

## 4. Data boundary and performance

- [ ] Accepted containers, dtypes, and semantic mappings are validated before expensive work.
- [ ] Copies, materialization, sorting, rechunking, and casting are visible or documented.
- [ ] Lazy and eager paths have equivalent semantics.
- [ ] Memory and thread budgets are respected, including nested libraries.
- [ ] Native/query-engine paths match the reference within declared tolerances.
- [ ] Performance claims include boundary cost, representative data, and repeatable measurements.
- [ ] A supported safe fallback exists or failure is clear and early.

## 5. Native safety

- [ ] Dimensions, offsets, null bitmaps, chunks, and integer conversions are checked.
- [ ] Panics and Rust implementation errors cannot cross the FFI boundary unhandled.
- [ ] Unsafe blocks are minimal and document their safety invariants.
- [ ] The GIL is released only while no Python objects are accessed.
- [ ] Rust core errors remain independent of Python.
- [ ] Rust unit, Python integration, differential, and concurrency tests cover the change.

## 6. Results, findings, and reporting

- [ ] Results include metrics, typed evidence, warnings/findings, provenance, and versions.
- [ ] Finding state and severity are independent and semantically correct.
- [ ] Missing evidence is `UNKNOWN`; inapplicable checks are `NOT_APPLICABLE`.
- [ ] Audit rule applicability, threshold, and rule version are explicit.
- [ ] Score coverage shows missing evidence and excludes non-applicable rules correctly.
- [ ] Renderers do not recompute or reinterpret analytical evidence.
- [ ] JSON is finite and schema-compatible; ordering/rounding are deterministic.
- [ ] Markdown/HTML and terminal output handle hostile/untrusted text safely.

## 7. Reproducibility and security

- [ ] Trial history includes failures, retries, and unselected candidates.
- [ ] Canonical parameters and fingerprints include all result-affecting state.
- [ ] Cache keys cannot reuse results across method/data/code/config/RNG changes.
- [ ] Completed records are append-only or migrated with provenance.
- [ ] Bundles validate paths and digests and avoid proprietary data by default.
- [ ] Secrets, tokens, signed URLs, environment values, and table contents are not logged.
- [ ] Plugins require explicit activation and are identified in provenance.
- [ ] SQL uses validation and parameter binding; untrusted artifacts are not unpickled.

## 8. Tests, docs, and compatibility

- [ ] Tests fail for the incorrect behavior rather than mirror the implementation.
- [ ] Regression tests name or explain the violated contract.
- [ ] Supported Python/Rust/platform constraints are preserved.
- [ ] Method, schema, rule, score, and bundle versions change when their meanings change.
- [ ] Subsystem/API documentation and examples match implemented status.
- [ ] `CHANGELOG.md` records user-visible changes.
- [ ] Focused and applicable full checks ran; unrun checks and risk are reported.

## Handoff severity

Treat temporal leakage, incorrect inference, silent data loss, unsafe FFI behavior, path traversal, credential exposure, and cache collisions that return wrong evidence as release-blocking. Treat missing docs, weak diagnostics, or incomplete secondary coverage according to their impact, but never hide them behind an aggregate score.
