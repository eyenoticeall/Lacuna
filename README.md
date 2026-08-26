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
> Lacuna **v0.7** adds deterministic, checksummed `.lacuna` reproducibility bundles with a published
> manifest schema, privacy redaction, hostile-archive defenses, and independent non-executing
> verification. The additive core `0.7.x` contract preserves every earlier compatibility fixture;
> `lacuna-options` `0.1.1` keeps the same API while expanding compatibility through core `0.7.x`.
> Lacuna remains pre-1.0 software; later minor versions may evolve through documented migrations.

> [!NOTE]
> [`v0.7.0` is distributed through GitHub Releases](https://github.com/eyenoticeall/Lacuna/releases/tag/v0.7.0)
> as checksummed, provenance-attested core and options wheels/source distributions. The PyPI
> distribution name `lacuna` belongs to an unrelated project, so do not install that package
> expecting this software.

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

| Area | Implemented behavior |
|---|---|
| Labels | Explicit observation/entry/exit timing, trading-observation horizons, censoring and adjustment evidence |
| Signal diagnostics | Pearson/Spearman IC, IC time series, balanced quantiles, spreads, monotonicity, turnover, and decay |
| Financial validation | Walk-forward, purged K-fold/CPCV paths, dependent and joint bootstrap, permutation, Sharpe/PSR/DSR, CSCV/PBO, Reality Check, and SPA |
| Audit and reports | Versioned rules, explicit unknown/not-applicable states, evidence coverage, JSON, Markdown, and self-contained HTML |
| Reproducibility | Deterministic `.lacuna` archives, published manifest schema, privacy redaction, SHA-256 integrity, and strict non-executing verification |
| Native core | Rust grouped-rank IC, bootstrap-mean reduction, and half-open interval purging with Python references |
| Data boundary | Polars eager/lazy, NumPy, optional pandas, and Arrow-compatible inputs |
| Quality | Published result schema, golden fixtures, property/reference/statistical/differential tests, and Python/Criterion benchmarks |
| Experiment lineage | Canonical fingerprints, append-only SQLite attempts/corrections, full eligible-set selection records, and structured snapshots |
| Multiplicity | Bonferroni, Holm, Benjamini-Hochberg, and Benjamini-Yekutieli adjustment over explicit or registered trial families |
| Robustness | Parameter surfaces, seeded continuous perturbation, declared subperiods, and timestamped universe composition evidence |
| Regimes | Fixed/trailing/retrospective quantile classifiers, availability checks, conditional evidence, and outcome concentration |
| Trading realism | Composable commissions, spread, slippage, impact, and borrow; stress grids, break-even costs, point-in-time liquidity, and capacity curves |
| Data correctness | Availability-safe as-of joins, revision/future-data checks, survivorship states, half-open membership, universe drift, and dataset contracts |
| Optional integrations | DuckDB Arrow streams, scikit-learn CV, immutable vendor schemas, explicit backtest artifact semantics, and metadata-only plugin discovery |
| Options extension | Separate typed package with normalized chains, carry forwards, log-forward moneyness, delta buckets, and empirical IV residuals |

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
report.bundle(
    "study.lacuna",
    provenance={"code_fingerprint": "git:abc123"},
)

verification = lc.verify_bundle("study.lacuna")
print(verification.archive_sha256)
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

Keep model-fitting CPCV separate from selection analysis, then test a declared strategy family
against one common benchmark:

```python
paths = lc.cv.CombinatorialPurgedKFold(
    n_groups=6,
    n_test_groups=2,
    embargo=2,
).split(labels.frame)

pbo = lc.validation.probability_of_backtest_overfitting(
    synchronous_strategy_returns,
    partitions=8,
    partition_sensitivity=(4, 6, 10),
)

spa = lc.validation.superior_predictive_ability(
    performance_differentials,
    expected_block_length=20,
    resamples=10_000,
    seed=42,
)
```

Record every tried variant before selecting a winner, then adjust the complete family:

```python
registry = lc.ExperimentRegistry("momentum-search", path="experiments.sqlite3")
for lookback, p_value in [(20, 0.03), (40, 0.01), (60, 0.20)]:
    registry.record(
        parameters={"lookback": lookback},
        metric=p_value,
        metric_name="p_value",
        method="strategy.evaluate",
        data_fingerprint="dataset:2026-08-26",
        code_fingerprint="git:abc123",
    )

adjusted = lc.validation.multiple_testing(registry, method="holm")
```

Stress normalized trades across explicit friction assumptions without hiding missing evidence:

```python
surface = lc.costs.stress(
    trades,
    spread_bps=(0, 2, 5, 10, 20),
    slippage_bps=(0, 2, 5, 10),
    capital=10_000_000,
    annualization=252,
)

curve = lc.costs.capacity_curve(
    trades,
    capital=(1_000_000, 5_000_000, 10_000_000),
    base_capital=1_000_000,
    scenarios=(lc.costs.CapacityScenario("base", impact_coefficient=0.10),),
    classification_mode="point_in_time",
    available_time="market_available_time",
)
```

Keep future information and current-only universes out of historical decisions:

```python
joined = lc.bias.asof_join(
    decisions,
    fundamentals,
    left_time="decision_time",
    right_time="available_time",
    by="instrument",
    revision="revision_id",
    revision_mode="point_in_time",
)

members = lc.bias.membership_at(
    index_membership,
    as_of=rebalance_time,
    identity=("index", "instrument"),
    source_status="confirmed_safe",
)
```

Cross external boundaries without hiding their semantics:

```python
duckdb_frame = lc.adapters.from_duckdb(executed_relation)

cv = lc.adapters.as_sklearn_cv(
    lc.cv.PurgedKFold(n_splits=5, embargo=1),
    label_intervals,
)

candidates = lc.plugins.discover_plugins(group="audit_rules")  # metadata only
plugin = lc.plugins.activate_plugin(candidates[0], required_capability="audit.signal")
```

The options package is independently versioned and imported separately:

```python
import lacuna_options as lo

chain = lo.validate_chain(option_quotes, year_basis=365.25)
bucketed = lo.delta_buckets(chain)
residuals = lo.empirical_residual(chain, expected="fair_iv")
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
  --out lacuna-audit.html \
  --bundle study.lacuna

uv run lacuna bundle verify study.lacuna
```

## Repository map

```text
.
├── python/lacuna/          # public Python package
├── rust/
│   ├── lacuna-core/        # language-independent kernels
│   └── lacuna-python/      # PyO3 extension
├── extensions/
│   └── lacuna-options/     # independently versioned optional distribution
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

Versions `0.1` through `0.5` cover foundations, signal diagnostics, temporal validation, dependent
bootstrap, audit/reporting, experiment lineage, multiple-testing correction, robustness,
trading-realism evidence, point-in-time data correctness, and advanced inference. Released `0.6`
adds optional adapters/plugins and the separate options package without expanding the core
dependency surface. Released `0.7` adds portable identifiable-level evidence bundles. Versions
`0.8`–`0.9` are reserved for cross-phase standardized audit, migration, performance, and real-user
hardening before a stable `1.0.0` contract.

See the [implementation roadmap](docs/development/roadmap.md) for the phase-to-version progression
and the full [technical specification](LACUNA_TECHNICAL_SPEC.md) for architecture and statistical
scope.

## Engineering handbook

The technical specification is backed by implementation-oriented documentation:

- [architecture and dependency boundaries](docs/concepts/architecture.md);
- [semantic time, identity, and table contracts](docs/concepts/data-model.md);
- [structured evidence and finding contracts](docs/concepts/evidence-model.md);
- [developer workflow, testing, native, performance, and release guides](docs/development/index.md);
- [subsystem contracts with formulas, invariants, failure modes, and tests](docs/subsystems/signal-labels.md);
- [coding-agent playbooks and review checklist](docs/agents/index.md).

The documentation distinguishes released v0.1–v0.7 behavior from later contracts. Contributors
and coding agents should begin with [AGENTS.md](AGENTS.md), then read the relevant methodology and
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
[release engineering contract](docs/development/release.md).

Contribution guidance lives in [CONTRIBUTING.md](CONTRIBUTING.md). The complete local documentation site can be built with `uv run mkdocs serve`. Security concerns should follow [SECURITY.md](SECURITY.md).

## License

Lacuna is dual-licensed under the [MIT License](LICENSE-MIT) or [Apache License 2.0](LICENSE-APACHE), at your option.

---

<div align="center">
  <img src="logos/lacuna-logo-icon.webp" alt="Lacuna mark" width="72" />
  <p><strong>Bring a signal or backtest. Lacuna will try to find the gaps in the evidence.</strong></p>
</div>
