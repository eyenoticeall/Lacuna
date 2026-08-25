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
    <a href="https://github.com/eyenoticeall/Lacuna/actions/workflows/ci.yml"><img src="https://github.com/eyenoticeall/Lacuna/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>&nbsp;&nbsp;
    <code>Python 3.11+</code>&nbsp;&nbsp;
    <code>Rust 2024</code>&nbsp;&nbsp;
    <code>Arrow-native</code>&nbsp;&nbsp;
    <code>MIT OR Apache-2.0</code>
  </p>
</div>

---

Lacuna is the validation and diagnostics layer between a quantitative research idea and confidence in its backtest. Bring a signal, a return stream, or an experiment history; Lacuna's job is to uncover weak evidence, leakage, instability, and unrealistic assumptions before capital is at risk.

> [!IMPORTANT]
> Lacuna is a **v0.1 release candidate**. The initial signal-validation path is implemented and
> tested, and the `0.1.x` public API contract is now reviewable and regression-tested. It remains
> pre-1.0 software; later minor versions may evolve through documented migrations.

> [!NOTE]
> [`v0.1.0-rc.1` is available for independent testing](https://github.com/eyenoticeall/Lacuna/releases/tag/v0.1.0-rc.1).
> Lacuna needs results from two non-implementers before the candidate can graduate. Follow the
> [tester protocol](docs/development/release-candidate-feedback.md), then submit the
> [structured feedback form](https://github.com/eyenoticeall/Lacuna/issues/new?template=rc-feedback.yml).
> Progress and qualifying reports are tracked in
> [GitHub issue #2](https://github.com/eyenoticeall/Lacuna/issues/2).

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

## What works now

| v0.1 area | Implemented behavior |
|---|---|
| Labels | Explicit observation/entry/exit timing, trading-observation horizons, censoring and adjustment evidence |
| Signal diagnostics | Pearson/Spearman IC, IC time series, balanced quantiles, spreads, monotonicity, turnover, and decay |
| Financial validation | Expanding/rolling walk-forward folds, purged K-fold, embargo, and IID/moving/circular/stationary bootstrap |
| Audit and reports | Versioned rules, explicit unknown/not-applicable states, evidence coverage, JSON, Markdown, and self-contained HTML |
| Native core | Rust grouped-rank IC, bootstrap-mean reduction, and half-open interval purging with Python references |
| Data boundary | Polars eager/lazy, NumPy, optional pandas, and Arrow-compatible inputs |
| Quality | Published result schema, golden fixtures, property/reference/statistical/differential tests, and Python/Criterion benchmarks |

## Quick start

Lacuna uses [uv](https://docs.astral.sh/uv/) for Python environments and Cargo for its Rust core.

```bash
git clone <your-fork-or-repository-url>
cd Lacuna

uv sync --group dev --group docs --extra pandas --extra statistics
uv run lacuna doctor
uv run pytest
cargo test --workspace
```

Inspect the runtime in machine-readable form:

```bash
uv run lacuna doctor --json
```

Turn a cross-sectional signal and price panel into structured evidence:

```python
import lacuna as lc

study = lc.SignalStudy(
    signal=signal,
    prices=prices,
    horizons=("1D", "5D", "20D"),
    signal_observed_at="open",
    entry="current_close",
    price_adjustment="total_return_adjusted",
    quantiles=5,
)

labels = study.labels()
split = lc.cv.PurgedKFold(n_splits=5, embargo=1).split(labels.frame)
report = study.audit(bootstrap_resamples=10_000, seed=42, split=split)
report.show()
report.to_json("lacuna-audit.json")
report.to_html("lacuna-audit.html")
```

Missing price-adjustment, delisting, survivorship, trial-history, or validation evidence stays visible
as `UNKNOWN`; it is never silently promoted to a pass.

The same methods are composable through the functional API:

```python
labels = lc.labels.forward_returns(
    prices,
    horizons=("1D", "5D", "20D"),
    price_adjustment="total_return_adjusted",
)
ic = lc.signal.ic(signal, labels, method="spearman")
quantiles = lc.signal.quantiles(signal, labels, quantiles=5)
uncertainty = lc.validation.bootstrap(
    [row["ic"] for row in ic.table("ic_by_period") if row["ic"] is not None],
    method="stationary",
    expected_block_length=5,
    resamples=10_000,
    seed=42,
)
```

For local Parquet, CSV, Arrow IPC, or Feather files:

```bash
uv run lacuna signal \
  --signal factor.parquet \
  --prices prices.parquet \
  --horizon 1D --horizon 5D --horizon 20D \
  --price-adjustment total_return_adjusted \
  --bootstrap-resamples 10000 \
  --seed 42 \
  --out lacuna-audit.html
```

## Repository map

```text
.
├── python/lacuna/          # public Python package
├── rust/
│   ├── lacuna-core/        # language-independent kernels
│   └── lacuna-python/      # PyO3 extension
├── tests/                  # unit, property, reference, schema, golden, and integration tests
├── benches/                # Python and Criterion benchmark entry points
├── schemas/                # published result compatibility schemas
├── docs/                   # engineering handbook and subsystem contracts
├── examples/               # executable examples
├── logos/                  # Lacuna brand assets
├── AGENTS.md               # repository contract for coding agents
├── pyproject.toml          # Python package and tooling
└── Cargo.toml              # Rust workspace
```

## Roadmap

The initial v0.1 path covers foundations, signal diagnostics, temporal validation, dependent
bootstrap, audit/reporting, interoperability, and benchmarks. Next milestones add robustness
surfaces, experiment history, cost/capacity evidence, and point-in-time data checks before advanced
inference and integrations.

See the full [technical specification](LACUNA_TECHNICAL_SPEC.md) for the architecture, statistical scope, and version milestones.

## Engineering handbook

The technical specification is backed by implementation-oriented documentation:

- [architecture and dependency boundaries](docs/concepts/architecture.md);
- [semantic time, identity, and table contracts](docs/concepts/data-model.md);
- [structured evidence and finding contracts](docs/concepts/evidence-model.md);
- [developer workflow, testing, native, performance, and release guides](docs/development/index.md);
- [subsystem contracts with formulas, invariants, failure modes, and tests](docs/subsystems/signal-labels.md);
- [coding-agent playbooks and review checklist](docs/agents/index.md).

The documentation distinguishes implemented v0.1 behavior from later contracts. Contributors and
coding agents should begin with [AGENTS.md](AGENTS.md), then read the relevant methodology and
subsystem pages before changing a method.

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
uv run maturin build --release

# Run reproducible benchmarks
uv run lacuna bench --tier smoke
cargo bench --bench kernels
```

Pull requests pass through formatting, lint, strict typing, Python 3.11–3.14 on Linux, Python 3.13
on macOS and Windows, Rust, optional dataframe/reference integrations, strict documentation, and a
minimum-Rust check, plus a clean source-distribution-to-wheel smoke test. See the
[CI architecture](docs/development/continuous-integration.md) for the job graph and branch-protection
contract.

Version-matching tags additionally build target-smoke-tested stable-ABI wheels for Linux x86_64,
Linux aarch64, macOS arm64, and Windows x86_64, then publish checksums and GitHub provenance. See the
[release engineering contract](docs/development/release.md) and
[independent feedback protocol](docs/development/release-candidate-feedback.md).

Contribution guidance lives in [CONTRIBUTING.md](CONTRIBUTING.md). The complete local documentation site can be built with `uv run mkdocs serve`. Security concerns should follow [SECURITY.md](SECURITY.md).

## License

Lacuna is dual-licensed under the [MIT License](LICENSE-MIT) or [Apache License 2.0](LICENSE-APACHE), at your option.

---

<div align="center">
  <img src="logos/lacuna-logo-icon.webp" alt="Lacuna mark" width="72" />
  <p><strong>Bring a signal or backtest. Lacuna will try to find the gaps in the evidence.</strong></p>
</div>
