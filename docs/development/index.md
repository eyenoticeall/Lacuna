# Developer handbook

This handbook translates Lacuna's product specification into engineering rules. Read the pages relevant to a change before editing code.

## Start here

| Change | Required reading |
|---|---|
| Any public API | [Python API](python-api.md), [API surface](../reference/python-api-surface.md), [Results and evidence](../concepts/evidence-model.md) |
| Dataframe or schema handling | [Data boundary](data-boundary.md), [Data and time](../concepts/data-model.md) |
| Rust or performance work | [Native core](native-core.md), [Performance](performance.md) |
| New statistical method | [Contributing a method](contributing-a-method.md), [Testing](testing.md) |
| Package or dependency change | [Repository layout](repository-layout.md), [Architecture](../concepts/architecture.md) |
| CI or required checks | [Continuous integration](continuous-integration.md), [Testing](testing.md) |
| Installation or runtime failure | [Installation diagnostics](installation-diagnostics.md), [Release engineering](release.md) |
| Release or persisted schema | [Release engineering](release.md), [Results and evidence](../concepts/evidence-model.md) |
| Roadmap work | [Implementation roadmap](roadmap.md), relevant [subsystem guide](../subsystems/signal-labels.md) |
| Bundle or portable evidence | [Reproducibility bundle](../reference/reproducibility-bundle.md), [Experiments](../subsystems/experiments-reproducibility.md) |
| Standardized audit profile | [Standardized audit](../reference/standardized-audit.md), [Audit subsystem](../subsystems/audit-reporting.md) |
| Stable-release claim | [v1 readiness ledger](v1-readiness.md), [Implementation roadmap](roadmap.md) |

Automation and coding agents must also follow the repository-root `AGENTS.md` and the [agent handbook](../agents/index.md).

## Engineering priorities

Ordered priorities are:

1. Temporal and statistical correctness.
2. Explicit assumptions and inspectable evidence.
3. Interoperability with ordinary research data.
4. Reproducibility and stable result contracts.
5. Measured performance and bounded memory.
6. Ergonomic progressive disclosure.

Performance does not excuse an incorrect or opaque method. Elegance does not excuse materializing an unbounded dataset. Convenience does not turn missing evidence into a pass.

## Change lifecycle

Every substantial analytical change follows this path:

```text
contract and assumptions
        ↓
reference implementation
        ↓
unit/reference/property tests
        ↓
public result and provenance
        ↓
benchmark and execution decision
        ↓
optional native optimization
        ↓
methodology and API documentation
```

Do not begin with a native optimization. The reference path is an executable definition and differential-test oracle.

## Local quality gate

```bash
uv sync --group dev --group docs

uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest

cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace

uv run mkdocs build --strict
uv build --wheel
```

Run checks proportional to the change while developing, then the full relevant gate before handoff. Statistical changes also run their reference and simulation suites. Performance changes include comparable benchmark results and memory measurements.

## Documentation contract

Documentation has four audiences:

- tutorials establish an end-to-end workflow;
- how-to guides solve a concrete task;
- API reference defines callable behavior;
- methodology explains formulas, assumptions, failure modes, and citations.

Subsystem architecture guides do not replace methodology pages. A method is not complete until a user can learn what it means and a developer can learn how its implementation is constrained.
