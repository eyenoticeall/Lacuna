<div align="center">
  <table>
    <tr>
      <td align="center" bgcolor="#0b0d0e">
        <img src="logos/lacuna-logo-lockup.png" alt="Lacuna" width="520" />
      </td>
    </tr>
  </table>

  <p><strong>Open-source quantitative research validation for finding where alpha breaks.</strong></p>
  <p><em>Stress-test your alpha before the market does.</em></p>

  <p>
    <code>Python 3.11+</code>&nbsp;&nbsp;
    <code>Rust 2024</code>&nbsp;&nbsp;
    <code>Arrow-native</code>&nbsp;&nbsp;
    <code>MIT OR Apache-2.0</code>
  </p>
</div>

---

Lacuna is the validation and diagnostics layer between a quantitative research idea and confidence in its backtest. Bring a signal, a return stream, or an experiment history; Lacuna's job is to uncover weak evidence, leakage, instability, and unrealistic assumptions before capital is at risk.

> [!IMPORTANT]
> Lacuna is at the **foundation / pre-alpha** stage. The package, native bridge, data boundary, result contracts, tests, CI, and documentation skeleton are in place. Signal analytics and audit workflows shown as “target API” below are the intended v0.1 experience, not released functionality yet.

## Why Lacuna?

Backtest engines are good at answering _what happened under these assumptions?_ Lacuna is being built to ask the harder follow-up questions:

- Is the signal informative before portfolio construction amplifies it?
- Did overlapping labels or unavailable data leak across the validation boundary?
- Does the result survive nearby parameters, different periods, and different regimes?
- Is the evidence still credible after research trials and transaction costs are counted?
- Can every conclusion be reproduced from structured, machine-readable evidence?

Lacuna is not a broker, market-data vendor, strategy generator, or full event-driven backtester. It is designed to sit on top of Polars, pandas, NumPy, Arrow, and existing research or backtesting systems.

## Architecture

```text
Your research stack
pandas · Polars · NumPy · Arrow · any backtester
                         │
                         ▼
              Typed Python API
                         │
              Arrow-compatible boundary
                         │
             ┌───────────┼───────────┐
             ▼           ▼           ▼
        Rust kernels  Polars ops  NumPy/SciPy
             └───────────┼───────────┘
                         ▼
        Structured results and findings
                         │
                    JSON · Markdown · HTML
```

The design keeps **Python outside, Rust inside**: Python supplies research ergonomics, Rust owns benchmark-justified hot paths, and Arrow-compatible columnar memory is the interoperability contract.

## What is in the scaffold?

| Foundation | Included now |
|---|---|
| Python package | Typed public API, scoped configuration, CLI diagnostics |
| Native core | Cargo workspace, PyO3/maturin bridge, checked numerical smoke kernel |
| Data boundary | Polars-first normalization for lazy/eager, NumPy, pandas, and Arrow-compatible inputs |
| Result contract | Immutable metadata, findings, metrics, tables, and safe JSON serialization |
| Quality | Python, property, integration, and Rust tests; Ruff, mypy, and CI configuration |
| Project docs | Architecture, subsystem contracts, developer handbook, agent playbooks, methodology, and roadmap |

## Quick start

Lacuna uses [uv](https://docs.astral.sh/uv/) for Python environments and Cargo for its Rust core.

```bash
git clone <your-fork-or-repository-url>
cd Lacuna

uv sync --group dev
uv run lacuna doctor
uv run pytest
cargo test --workspace
```

Inspect the runtime in machine-readable form:

```bash
uv run lacuna doctor --json
```

The initial public contracts are usable today:

```python
import lacuna as lc

with lc.config(threads=8, seed=42) as active:
    result = lc.AnalysisResult(
        metadata=lc.ResultMetadata(
            method="research.example",
            parameters={"threads": active.threads},
            seed=active.seed,
        ),
        metrics={"observations": 1_000_000},
        findings=(
            lc.Finding(
                code="TRIAL_HISTORY_MISSING",
                title="Trial history unavailable",
                message="Multiple-testing risk cannot be estimated.",
                state=lc.FindingState.UNKNOWN,
                severity=lc.Severity.HIGH,
            ),
        ),
    )

print(result.to_json())
```

### Target v0.1 API

The first product milestone is intentionally narrow: turn a cross-sectional signal into rigorous diagnostics.

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

The same evidence should remain composable through a functional API:

```python
ic = lc.signal.ic(signal, forward_returns, method="spearman", by="date")
```

## Repository map

```text
.
├── python/lacuna/          # public Python package
├── rust/
│   ├── lacuna-core/        # language-independent kernels
│   └── lacuna-python/      # PyO3 extension
├── tests/                  # unit, property, and integration tests
├── benches/                # benchmark entry points
├── docs/                   # engineering handbook and subsystem contracts
├── examples/               # executable examples
├── logos/                  # Lacuna brand assets
├── AGENTS.md               # repository contract for coding agents
├── pyproject.toml          # Python package and tooling
└── Cargo.toml              # Rust workspace
```

## Roadmap

1. **Foundations** — build, data boundary, result model, tests, benchmarks, docs.
2. **Signal diagnostics** — forward returns, Pearson/Spearman IC, quantiles, decay, turnover.
3. **Validation** — block bootstrap, walk-forward analysis, purging, and embargo.
4. **Audit** — explicit `PASS`, `WARN`, `FAIL`, `UNKNOWN`, and `NOT_APPLICABLE` findings.
5. **Robustness and realism** — parameter stability, regimes, cost stress, capacity, and point-in-time correctness.

See the full [technical specification](LACUNA_TECHNICAL_SPEC.md) for the architecture, statistical scope, and version milestones.

## Engineering handbook

The technical specification is backed by implementation-oriented documentation:

- [architecture and dependency boundaries](docs/concepts/architecture.md);
- [semantic time, identity, and table contracts](docs/concepts/data-model.md);
- [structured evidence and finding contracts](docs/concepts/evidence-model.md);
- [developer workflow, testing, native, performance, and release guides](docs/development/index.md);
- [subsystem contracts with formulas, invariants, failure modes, and tests](docs/subsystems/signal-labels.md);
- [coding-agent playbooks and review checklist](docs/agents/index.md).

The documentation distinguishes the implemented Phase 0 foundation, the v0.1 contract, and later work. Contributors and coding agents should begin with [AGENTS.md](AGENTS.md) before implementing target APIs.

## Principles

- **Time is part of the type system.** Event, availability, effective, revision, and label times are not interchangeable.
- **Unknown is not pass.** Missing evidence stays visible.
- **Results before reports.** Every visualization is backed by structured, inspectable data.
- **Robustness means neighborhoods, not points.** Isolated optima are warnings, not trophies.
- **Performance claims require benchmarks.** Native code is earned through measurement.
- **Interoperate instead of replacing.** Lacuna complements existing research stacks.

## Development

```bash
# Format and lint
uv run ruff format --check .
uv run ruff check .
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings

# Type-check and test
uv run mypy
uv run pytest
cargo test --workspace

# Build a local wheel
uv build --wheel
```

Contribution guidance lives in [CONTRIBUTING.md](CONTRIBUTING.md). The complete local documentation site can be built with `uv run mkdocs serve`. Security concerns should follow [SECURITY.md](SECURITY.md).

## License

Lacuna is dual-licensed under the [MIT License](LICENSE-MIT) or [Apache License 2.0](LICENSE-APACHE), at your option.

---

<div align="center">
  <img src="logos/lacuna-logo-icon.webp" alt="Lacuna mark" width="72" />
  <p><strong>Bring a signal or backtest. Lacuna will try to find the gaps in the evidence.</strong></p>
</div>
