# AGENTS.md

This file is the repository-wide operating contract for coding agents working on Lacuna. It applies to the entire repository unless a more specific `AGENTS.md` is added below a directory. User instructions and repository policy take precedence over this guide.

Lacuna is pre-alpha quantitative research-validation infrastructure. Correct temporal and statistical semantics matter more than feature count or benchmark wins. An implementation is incomplete until its assumptions, evidence, failure behavior, and tests are visible.

## Start here

Before changing code:

1. Read `LACUNA_TECHNICAL_SPEC.md` for the product and methodology intent.
2. Read `docs/concepts/architecture.md` for dependency boundaries and implementation status.
3. Read `docs/concepts/data-model.md` and `docs/concepts/evidence-model.md` for shared contracts.
4. Read the relevant guide in `docs/subsystems/`.
5. Read the relevant engineering guide in `docs/development/`.
6. Inspect nearby code and tests before proposing new abstractions.

Do not infer that an API exists because it appears in target documentation. Documents label implemented behavior, the v0.1 contract, and later work separately.

## Route changes to the right guidance

| Change | Required guide |
| --- | --- |
| public Python API | `docs/development/python-api.md` |
| Arrow, Polars, pandas, or lazy inputs | `docs/development/data-boundary.md` |
| Rust/PyO3 kernel | `docs/development/native-core.md` |
| analytical/statistical method | `docs/development/contributing-a-method.md` and `docs/development/testing.md` |
| signal, labels, or IC | `docs/subsystems/signal-labels.md` |
| cross-validation, bootstrap, or Sharpe inference | `docs/subsystems/financial-validation.md` |
| robustness analysis | `docs/subsystems/robustness.md` |
| costs or capacity | `docs/subsystems/costs-capacity.md` |
| point-in-time or bias logic | `docs/subsystems/bias-point-in-time.md` |
| audit rule or report | `docs/subsystems/audit-reporting.md` |
| experiment registry or cache | `docs/subsystems/experiments-reproducibility.md` |
| adapter, execution planner, CLI, or plugin | `docs/subsystems/adapters-execution-plugins.md` |
| performance work | `docs/development/performance.md` |
| package/release work | `docs/development/release.md` |

Use `docs/agents/implementation-playbook.md` for the step-by-step workflow and `docs/agents/review-checklist.md` before handoff.

## Non-negotiable architecture

- Public Python APIs own validation, orchestration, configuration, provenance, warnings, and result construction.
- Rust owns proven computational kernels, not user-facing policy.
- `lacuna-core` is Python-independent. `lacuna-python` contains PyO3 conversions and exception mapping.
- Python modules may call the native extension; native crates must not depend on Python application code.
- Analytical modules return structured evidence. Audit rules consume evidence. Renderers only present stored evidence.
- Adapters translate containers and source metadata; they do not silently choose research methodology.
- Experiment storage records executions; it does not calculate statistics.
- The CLI delegates to public Python services and must not contain unique analytical logic.
- Optional integrations stay optional. Core import must work without pandas, SciPy, plotting, ML, or database extras.
- Add target packages incrementally with working behavior; do not create empty architecture placeholders.

If a change needs to reverse a dependency or blend these responsibilities, document the decision in `docs/reference/architecture-decisions.md` before implementing it.

## Temporal and data rules

Treat these rules as correctness requirements:

- Distinguish event, observation, availability, effective, revision, decision, execution, and label times.
- An economic effective date is not an availability timestamp.
- A right-side record used at a decision must satisfy `available_time <= decision_time` unless a stricter cutoff applies.
- Use half-open time intervals `[start, end)` for labels, folds, membership, and embargo ranges.
- Stable `instrument_id` is the primary entity identity. Tickers are display/source attributes, not durable keys.
- Declare calendar, timezone, session, price field, corporate-action, currency, and return conventions.
- Declare whether data must be sorted and whether the function verifies, restores, or rejects ordering.
- Resolve duplicate keys explicitly. Never make row order an undocumented tie-breaker.
- Define null, NaN, infinity, and small-sample behavior independently.
- Avoid mutation of caller-owned inputs. Document unavoidable copies and materialization.
- Preserve lazy execution only when semantics remain equivalent; otherwise expose the collection boundary.
- Historical joins use the version available at the decision time, not the latest revision.
- If the source cannot establish point-in-time safety, return `UNKNOWN`; do not claim a pass.

Every feature working with time or entities needs fixtures that make leakage and identity errors observable.

## Statistical method rules

Before optimizing or exposing a method:

1. State the estimand or research question.
2. Define the mathematical procedure and assumptions.
3. Define sample eligibility, missing-data policy, weights, ties, and degrees of freedom.
4. Define output tables, metrics, findings, warnings, and provenance.
5. Assign a method version.
6. Implement or identify a slow, legible reference.
7. Validate with analytical fixtures, independent implementations, or controlled simulation.
8. Test edge cases and metamorphic properties.
9. Add dispatch/optimization only after correctness is established.

Never silently substitute a different method because an optional dependency is missing. Either use a validated equivalent implementation and record it, or raise a clear dependency/capability error.

Randomized methods must use an explicit algorithm and seed/root entropy, derive deterministic substreams from stable task identities, and return the RNG metadata in provenance. Worker scheduling must not change results.

Do not report more certainty than the method justifies. Capture warnings for weak assumptions, inadequate samples, degenerate variance, or incomplete evidence.

## Numerical behavior

- Use float64 for inferential calculations unless a method explicitly validates another precision.
- Define accumulation, overflow, zero-variance, and finite-value behavior.
- Compare implementations with method-specific absolute and relative tolerances.
- Do not use exact floating equality except for deliberately exact invariants.
- Keep full precision in stored evidence and round only in presentation.
- JSON must never emit NaN or infinity; use null plus an explanatory state/finding.
- Parallel reductions need a documented determinism policy and tighter tests around partition boundaries.
- A faster result that differs outside the declared tolerance is a correctness bug, not a benchmark tradeoff.

## Public Python APIs

- Prefer small functional APIs first. Stateful study objects must delegate to the same services.
- Use keyword-only parameters for policies that are easy to confuse.
- Type public inputs and outputs precisely; avoid exposing `Any` as the escape hatch for container support.
- Normalize configuration once and record the resolved configuration.
- Validate cheap structural conditions before materializing large inputs.
- Raise specific errors for invalid contracts; use warnings/findings for valid but weak evidence.
- Return immutable or effectively immutable `AnalysisResult` values.
- Keep internal modules private and re-export deliberately from package boundaries.
- Do not perform I/O, import optional heavy dependencies, configure logging, or initialize thread pools at import time.
- Preserve the lowest supported Python version declared in `pyproject.toml`.

## Rust and PyO3

Move work to Rust only when profiling shows a meaningful bottleneck and the operation has a stable, testable contract. A native kernel needs:

- a Python reference implementation or authoritative fixtures;
- coarse-grained inputs and outputs;
- Arrow-compatible or buffer-oriented transfer where practical;
- checked dimensions, offsets, null bitmaps, and integer conversions;
- explicit handling of empty, null-heavy, non-contiguous, and chunked inputs;
- no panic across the FFI boundary;
- Python exception mapping in `lacuna-python`;
- interpreter-lock release for independent work;
- thread-budget compliance;
- differential and property tests;
- benchmark evidence including transfer cost and peak memory.

Avoid per-row Python/Rust calls. Keep unsafe code narrowly scoped, justified by a safety comment, and covered by boundary tests. `lacuna-core` errors should be typed and Python-agnostic.

## Results, evidence, and audit behavior

- `AnalysisResult` is the common analytical boundary: metrics, typed tables, findings, provenance, warnings, and versions.
- Results should answer what was computed, on which data, using which assumptions, with what uncertainty, and by which implementation.
- Findings have separate state and severity. Use `PASS`, `WARN`, `FAIL`, `UNKNOWN`, and `NOT_APPLICABLE` consistently.
- Missing evidence produces `UNKNOWN`; inapplicable methodology produces `NOT_APPLICABLE`.
- Audit rules are deterministic, versioned, independently executable, and explicit about required evidence.
- Rule exceptions fail the audit by default; do not swallow internal errors as successful findings.
- Reports render stored evidence. They do not recalculate methods, change thresholds, or reinterpret states.
- Escape source-derived text in Markdown/HTML and exclude secrets, arbitrary raw data, and exception dumps from findings.
- Generated output has deterministic ordering and canonical, finite JSON values.

## Experiments and provenance

- Record every attempted trial, including failures and retries; do not keep only winners.
- Completed attempt records are append-only. Corrections create superseding records.
- Parameter serialization is canonical, versioned, and rejects ambiguous values.
- Fingerprints include method, parameters, semantic configuration, data/code identity, and RNG/backend details when material.
- A cache hit requires every result-affecting component to be known and equal.
- Selection records preserve the full eligible candidate set and criterion.
- Reproducibility claims distinguish identifiable, recomputable, numerically reproducible, and bitwise reproducible.
- Bundles must not include credentials, signed tokens, unredacted environment variables, or proprietary input data by default.

## Testing expectations

Choose tests by risk, not line count.

Every analytical method normally needs:

- focused unit tests;
- known analytical or literature fixtures;
- property/metamorphic tests;
- adversarial null/NaN/infinity and small-sample cases;
- temporal boundary cases when time is involved;
- deterministic randomized tests when simulation is involved;
- backend differential tests when more than one implementation exists.

Add statistical simulation tests only with declared seeds, expected error rates, and tolerances that are robust to supported platforms. Avoid fragile tests that merely replay the implementation's own formula.

Adapter changes need eager/lazy, chunked, dtype, ordering, duplicate, and copy/materialization cases. Native changes need Rust unit tests, Python integration tests, differential tests, and packaging smoke coverage. Report changes need schema round-trips, escaping tests, and intentionally reviewed golden artifacts.

A regression test should fail for the original bug before the fix and describe the violated contract in its name or comments.

## Performance work

- Benchmark before and after with representative shapes, null densities, grouping cardinalities, and chunk layouts.
- Include boundary conversion and allocation cost, not just the inner loop.
- Measure latency, throughput, peak memory, copies/materializations, and thread count.
- Compare against the validated reference and keep correctness checks in the benchmark path.
- Use the shared thread budget; avoid nested full-size pools.
- Prefer algorithmic and allocation improvements before adding complexity or dependencies.
- Do not claim a regression/improvement from a single noisy run. Preserve benchmark configuration and environment metadata.

## Dependencies, plugins, and security

- New runtime dependencies need a clear owner, purpose, optionality decision, maintenance assessment, and license/security review.
- Prefer existing stdlib, NumPy, Polars, Arrow, or Rust capabilities when they meet the contract.
- Optional dependencies are imported at the use site and fail with an actionable installation message.
- Plugin discovery does not authorize execution. Require explicit activation and record plugin identity/version.
- Python plugins are trusted code; do not imply process isolation.
- Never interpolate untrusted values or identifiers into SQL.
- Never unpickle untrusted artifacts.
- Validate bundle/output paths against their intended root and refuse traversal.
- Do not log table contents, tokens, credentials, signed URLs, or full environment dumps.

## Implementation workflow

For a normal feature or fix:

1. **Inspect** — locate the current boundary, tests, and documentation; note unrelated working-tree changes.
2. **Contract** — write down inputs, outputs, invariants, edge behavior, versions, and ownership.
3. **Reference** — implement the simplest clear version or a failing regression fixture.
4. **Validate** — compare with analytical expectations or an independent implementation.
5. **Implement** — make the smallest coherent production change.
6. **Optimize** — only if measurement justifies it; keep reference/differential coverage.
7. **Evidence** — include provenance, warnings, findings, and execution details required by the contract.
8. **Document** — update the subsystem/API guide and changelog for user-visible behavior.
9. **Verify** — run focused tests first, then the applicable repository gates.
10. **Review** — use `docs/agents/review-checklist.md` and report residual risk honestly.

Do not perform unrelated cleanup or overwrite user changes. Keep commits conceptually focused when commits are requested.

## Validation commands

Set up development and documentation dependencies:

```bash
uv sync --group dev --group docs
```

Python checks:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

Rust checks:

```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

Documentation and package checks:

```bash
uv run mkdocs build --strict
uv build
```

Run the smallest relevant test while iterating, but do not present an unrun gate as successful. If a check cannot run, state the exact command, reason, and remaining risk.

## Definition of done

A change is ready for handoff when:

- the implementation matches a documented contract and dependency boundary;
- temporal, missing-data, numerical, and failure policies are explicit;
- structured results contain necessary provenance and versions;
- correctness tests cover normal and adversarial paths;
- alternative backends agree within declared tolerance;
- performance claims have reproducible evidence;
- public behavior and roadmap/status docs are updated;
- user changes are preserved;
- relevant checks have run and the outcome is reported.

## Handoff format

End implementation work with:

- the outcome and affected public behavior;
- the principal files changed;
- validation commands and their results;
- any compatibility, numerical, performance, or security caveats;
- intentionally deferred work.

Avoid vague statements such as “tests should pass.” Separate verified facts from recommendations.
