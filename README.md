<div align="center">
  <table>
    <tr>
      <td align="center" bgcolor="#0b0d0e">
        <img src="https://raw.githubusercontent.com/eyenoticeall/Lacuna/main/logos/lacuna-logo-lockup.png" alt="Lacuna" width="520" />
      </td>
    </tr>
  </table>

  <p><strong>Open-source quantitative research validation for finding where alpha breaks.</strong></p>
  <p><em>Stress-test your alpha before the market does.</em></p>

  <p>
    <a href="https://github.com/eyenoticeall/Lacuna/actions/workflows/ci.yml"><img src="https://github.com/eyenoticeall/Lacuna/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>&nbsp;&nbsp;
    <a href="https://github.com/eyenoticeall/Lacuna/releases/latest"><img src="https://img.shields.io/github/v/release/eyenoticeall/Lacuna?display_name=tag&amp;sort=semver&amp;style=flat" alt="Latest release" /></a>&nbsp;&nbsp;
    <a href="https://pypi.org/project/lacuna-quant/"><img src="https://img.shields.io/pypi/v/lacuna-quant?label=PyPI&amp;logo=pypi&amp;logoColor=white&amp;style=flat" alt="PyPI" /></a>&nbsp;&nbsp;
    <a href="https://github.com/eyenoticeall/Lacuna/blob/main/pyproject.toml"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&amp;logoColor=white&amp;style=flat" alt="Python 3.11+" /></a>&nbsp;&nbsp;
    <a href="https://github.com/eyenoticeall/Lacuna/blob/main/Cargo.toml"><img src="https://img.shields.io/badge/Rust-2024-000000?logo=rust&amp;logoColor=white&amp;style=flat" alt="Rust 2024" /></a>&nbsp;&nbsp;
    <a href="https://github.com/eyenoticeall/Lacuna/blob/main/docs/development/data-boundary.md"><img src="https://img.shields.io/badge/Arrow-compatible-2563EB?logo=apachearrow&amp;logoColor=white&amp;style=flat" alt="Arrow compatible" /></a>&nbsp;&nbsp;
    <a href="https://github.com/eyenoticeall/Lacuna/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-3DA639?style=flat" alt="MIT License" /></a>
  </p>
</div>

---

Lacuna is the validation and diagnostics layer between a quantitative research idea and confidence in its backtest. Bring a signal, a return stream, or an experiment history; Lacuna's job is to uncover weak evidence, leakage, instability, and unrealistic assumptions before capital is at risk.

> [!IMPORTANT]
> **v0.13.0 is the current release.** It completes the planned factor-research sequence: explicit
> signal transformations and multi-lag stability in v0.10, validated decay inference, diagnostic
> portfolio projections, and event studies in v0.11, and semantics-first factor-panel ingestion in
> v0.12. Version 0.13 moves distribution to PyPI without changing the `lacuna` import API or
> analytical methods. Lacuna remains alpha software and its pre-1.0 APIs may evolve through
> documented migrations.

> [!NOTE]
> Install the core project from PyPI as `lacuna-quant`; Python code continues to use
> `import lacuna`. The PyPI project named `lacuna` is unrelated and must not be installed beside
> `lacuna-quant` because both own the same import-package path.

## Get started

Install the current release from PyPI, then verify the package, native extension, dependency
metadata, bundled schemas, and platform support in one command:

```bash
python -m pip install lacuna-quant
lacuna doctor --strict
```

The distribution is named `lacuna-quant`; Python code and the command line continue to use
`lacuna`. Stable-ABI wheels support CPython 3.11 and later on Linux x86-64 and arm64, macOS arm64,
and Windows x86-64.

Install only the optional method families you need:

```bash
python -m pip install "lacuna-quant[statistics,report,pandas]"
python -m pip install lacuna-options
```

Start with the [guided signal audit](https://github.com/eyenoticeall/Lacuna/blob/main/docs/getting-started/index.md),
review the [v0.13.0 release](https://github.com/eyenoticeall/Lacuna/releases/tag/v0.13.0), or use the
[Alphalens migration guide](https://github.com/eyenoticeall/Lacuna/blob/main/docs/getting-started/alphalens-migration.md)
when bringing an existing factor workflow.

If you installed a historical GitHub wheel whose distribution metadata was `lacuna`, remove it
before migrating; the unrelated PyPI project with that name is not Lacuna:

```bash
python -m pip uninstall lacuna lacuna-options
python -m pip install --upgrade lacuna-quant
```

Reinstall `lacuna-options` afterward only if your research uses the extension.

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

Python owns public contracts, temporal and statistical policy, provenance, and result construction.
Most current computation runs through Polars, NumPy, or optional SciPy. The compiled Rust extension
is deliberately narrow: it currently accelerates grouped rank IC, bootstrap-mean reduction, and
half-open interval purging, plus built-in PBO/CSCV partition reduction above its measured crossover,
each with a tested Python reference. Arrow-compatible columnar data is the interoperability
contract; additional Rust kernels require end-to-end profiling and differential evidence.

## What works now

| Area | Implemented on main for the v0.14 release target |
|---|---|
| Labels and timing | Explicit observation, availability, entry, and label-end times; half-open intervals; trading-observation horizons; censoring, adjustment, and delisting evidence |
| Factor diagnostics | Group-aware Pearson/Spearman IC; balanced, tie-preserving, split-aware, threshold, equal-width, and fixed-edge buckets; bucket returns and attrition |
| Signal transformations | Availability-checked weighted least-squares neutralization with coefficient, rank, condition, residual-DF, and fit evidence |
| Stability and decay | Exact multi-lag rank, autocorrelation, and membership turnover; descriptive decay plus validated exponential half-life inference |
| Diagnostic portfolios | Explicit long/short bucket projections with gross/net reconciliation, group neutrality, concentration, contribution, and target-turnover evidence—without compounding or execution simulation |
| Event studies | Availability-anchored windows, overlap and censoring evidence, clustered stationary-bootstrap intervals, and simultaneous response bands |
| Temporal and statistical validation | Walk-forward, purged K-fold and CPCV paths; IID/dependent/joint bootstrap; permutation; Sharpe/PSR/DSR; CSCV/PBO; Reality Check and SPA |
| Robustness and trial history | Parameter surfaces, seeded perturbations, subperiods, point-in-time regimes, universe scenarios, append-only experiment lineage, and multiple-testing correction |
| Trading realism | Composable commission, spread, slippage, impact, and borrow assumptions; stress surfaces, break-even analysis, liquidity evidence, and capacity curves |
| Point-in-time correctness | Availability-safe as-of joins, revision and future-data checks, survivorship states, half-open membership, universe drift, and dataset contracts |
| Evidence and reporting | Immutable `AnalysisResult` evidence; signal/strategy/options audit profiles; deterministic JSON and Markdown; core HTML and optional evidence-native Plotly HTML |
| Reproducibility | Deterministic `.lacuna` archives, published schemas, privacy redaction, SHA-256 integrity, and bounded non-executing verification |
| Interoperability | Eager/lazy Polars, NumPy, Arrow, optional pandas and named MultiIndexes, generic factor/vendor/backtest schemas, DuckDB Arrow streams, and scikit-learn CV |
| Native acceleration | Single-threaded Rust grouped-rank IC, bootstrap-mean, interval-purge, and admitted PBO reducers with checked bulk-array boundaries and callable references |
| Options extension | Independently versioned `lacuna-options` 0.2.0, with a 0.2.1 release target widening core compatibility through v0.14 without API changes |

Lacuna intentionally does **not** generate alpha, source market data, compound a portfolio, resolve
overlapping holdings, simulate orders or fills, route trades, or run live strategies. It also does
not infer calendars, execution timing, data availability, or backtester semantics from convenient
defaults.

## Research workflows

Lacuna accepts explicit research artifacts and returns structured evidence before rendering a
report. The complete study below uses the `statistics` and `report` extras installed in the
[Get started](#get-started) section.

Turn a cross-sectional signal and price panel into structured evidence:

```python
import lacuna as lc

study = lc.SignalStudy(
    signal=signal,
    prices=prices,
    horizons=("1D", "5D", "10D", "20D"),
    signal_observed_at="open",
    entry="current_close",
    price_adjustment="total_return_adjusted",
    quantiles=5,
)

labels = study.labels()
split = lc.cv.PurgedKFold(n_splits=5, embargo=1).split(labels.frame)
bucketed = study.bucketize(spec=lc.BucketSpec.quantiles(count=5))
bucket_returns = study.bucket_returns(bucketed)
multi_lag = study.turnover(lags=(1, 5, 20))
decay_fit = study.fit_decay(resamples=2_000, seed=42)
projection = study.portfolio_projection(
    bucketed,
    horizon="5D",
    long_buckets=(5,),
    short_buckets=(1,),
    gross_exposure=1.0,
    net_exposure=0.0,
)

report = study.audit(
    bootstrap_resamples=10_000,
    seed=42,
    split=split,
    additional_evidence={
        "bucket_returns_explicit": bucket_returns,
        "multi_lag_stability": multi_lag,
        "decay_fit": decay_fit,
        "portfolio_projection": projection.evidence,
    },
)
report.show()
report.to_json("lacuna-audit.json")
report.to_html("lacuna-audit.html", renderer="plotly", view="signal")
report.bundle(
    "study.lacuna",
    provenance={"code_fingerprint": "git:abc123"},
)

verification = lc.verify_bundle("study.lacuna")
print(verification.archive_sha256)
```

Missing price-adjustment, delisting, survivorship, trial-history, or validation evidence stays visible
as `UNKNOWN`; it is never silently promoted to a pass.

Compose evidence from every released phase with a scope-specific standardized profile:

```python
evidence = {
    "purged_split": split.evidence,
    "trials": registry.snapshot(),
    "costs": cost_stress,
    "future_data": future_data_check,
    "vendor": adapted_vendor.evidence,
    "backtest": adapted_returns.evidence,
}

standard = lc.standard_audit(results=evidence, scope="strategy")
print(standard.table("category_coverage"))
standard.bundle("strategy-audit.lacuna", evidence=evidence)
```

The profile distinguishes required, optional, and not-applicable evidence, carries domain findings
forward without changing their meaning, and deliberately emits no universal strategy-quality score.

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

Anchor event studies to when information became available—not merely when the underlying event
occurred:

```python
windows = lc.events.event_windows(
    events,
    prices,
    anchor="available_time",
    before=5,
    after=10,
    overlap_policy="raise",
    price_adjustment="total_return_adjusted",
)
response = lc.events.event_response(
    windows,
    resamples=2_000,
    seed=42,
)
```

Cross external boundaries without hiding their semantics:

```python
factor_schema = lc.adapters.FactorPanelSchema(
    schema_id="research.factor.v1",
    columns={
        "observation_time": "date",
        "instrument": "asset_id",
        "signal": "factor",
        "forward_return": "forward_5d",
    },
    semantics=lc.adapters.FactorPanelSemantics(
        signal_observation="market close",
        decision_time_rule="next session open",
        forward_return_entry="next session open",
        forward_return_exit="fifth session close",
        horizon_clock="trading observations",
        timezone="UTC",
        calendar="XNYS",
        adjustment_policy="total return adjusted",
        group_availability="unknown",
        imported_bucket_definition="not imported",
    ),
)
factor_panel = lc.adapters.adapt_factor_panel(raw_factor_data, factor_schema)

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
lacuna signal \
  --signal factor.parquet \
  --prices prices.parquet \
  --horizon 1D --horizon 5D --horizon 20D \
  --signal-observed-at open \
  --entry current_close \
  --price-adjustment total_return_adjusted \
  --bootstrap-resamples 10000 \
  --seed 42 \
  --out lacuna-audit.html \
  --html-renderer plotly \
  --bundle study.lacuna

lacuna bundle verify study.lacuna

lacuna audit \
  --scope strategy \
  --evidence split=purged-split.json \
  --evidence costs=cost-stress.json \
  --evidence bias=future-data.json \
  --out strategy-audit.html \
  --bundle strategy-audit.lacuna
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
├── benches/                # Python benchmark entry points
├── schemas/                # published result compatibility schemas
├── docs/                   # engineering handbook and subsystem contracts
├── examples/               # executable examples
├── logos/                  # Lacuna brand assets
├── AGENTS.md               # repository contract for coding agents
├── pyproject.toml          # Python package and tooling
└── Cargo.toml              # Rust workspace
```

## Roadmap and maturity

The planned `0.1`–`0.13` milestones are implemented, compatibility-fixtured, and released. The
current `0.13` line adds verified PyPI distribution while retaining the complete factor-research
sequence and Lacuna's explicit no-backtester boundary. The v0.14 implementation is complete but
release-gated: grouped IC and PBO remain provisional until pinned Linux, same-wheel ABI, target
wheel, and exact-SHA non-publishing preflight evidence promote every migration decision to a
terminal state.

Every repository-controlled item in the v1 readiness ledger has implementation evidence. `1.0.0`
remains blocked by one intentionally external requirement: real users must apply Lacuna to
independent research stacks. Until then, work should emphasize adoption feedback, compatibility,
correctness, and measured performance rather than accumulating speculative features.

See the [implementation roadmap](https://github.com/eyenoticeall/Lacuna/blob/main/docs/development/roadmap.md)
for the phase-to-version progression and the
[v1 readiness ledger](https://github.com/eyenoticeall/Lacuna/blob/main/docs/development/v1-readiness.md)
for the remaining gate. The full
[technical specification](https://github.com/eyenoticeall/Lacuna/blob/main/LACUNA_TECHNICAL_SPEC.md)
defines the architecture and statistical scope.

## Engineering handbook

The technical specification is backed by implementation-oriented documentation:

- [architecture and dependency boundaries](https://github.com/eyenoticeall/Lacuna/blob/main/docs/concepts/architecture.md);
- [semantic time, identity, and table contracts](https://github.com/eyenoticeall/Lacuna/blob/main/docs/concepts/data-model.md);
- [structured evidence and finding contracts](https://github.com/eyenoticeall/Lacuna/blob/main/docs/concepts/evidence-model.md);
- [developer workflow, testing, native, performance, and release guides](https://github.com/eyenoticeall/Lacuna/blob/main/docs/development/index.md);
- [subsystem contracts with formulas, invariants, failure modes, and tests](https://github.com/eyenoticeall/Lacuna/blob/main/docs/subsystems/signal-labels.md);
- [factor-research migration from Alphalens Reloaded](https://github.com/eyenoticeall/Lacuna/blob/main/docs/getting-started/alphalens-migration.md);
- [coding-agent playbooks and review checklist](https://github.com/eyenoticeall/Lacuna/blob/main/docs/agents/index.md).

The documentation distinguishes released v0.1–v0.13 behavior, release-gated v0.14 work, and later
contracts. Contributors and coding agents should begin with
[AGENTS.md](https://github.com/eyenoticeall/Lacuna/blob/main/AGENTS.md), then read the relevant
methodology and subsystem pages before changing a method.

## Principles

- **Time is part of the type system.** Event, availability, effective, revision, and label times are not interchangeable.
- **Unknown is not pass.** Missing evidence stays visible.
- **Results before reports.** Every visualization is backed by structured, inspectable data.
- **Robustness means neighborhoods, not points.** Isolated optima are warnings, not trophies.
- **Performance claims require benchmarks.** Native code is earned through measurement.
- **Interoperate instead of replacing.** Lacuna complements existing research stacks.

## Development

Lacuna uses [uv](https://docs.astral.sh/uv/) for Python environments and Cargo for the Rust
workspace:

```bash
git clone https://github.com/eyenoticeall/Lacuna.git
cd Lacuna
uv sync --group dev --group docs --extra pandas --extra statistics --extra report
```

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
[CI architecture](https://github.com/eyenoticeall/Lacuna/blob/main/docs/development/continuous-integration.md)
for the job graph and branch-protection contract.

Version-matching tags additionally build target-smoke-tested stable-ABI wheels for Linux x86_64,
Linux aarch64, macOS arm64, and Windows x86_64, then publish checksums and GitHub provenance. See the
[release engineering contract](https://github.com/eyenoticeall/Lacuna/blob/main/docs/development/release.md).

Contribution guidance lives in
[CONTRIBUTING.md](https://github.com/eyenoticeall/Lacuna/blob/main/CONTRIBUTING.md). The complete local
documentation site can be built with `uv run mkdocs serve`. Security concerns should follow
[SECURITY.md](https://github.com/eyenoticeall/Lacuna/blob/main/SECURITY.md).

## License

The current repository and future distributions are released under the
[MIT License](https://github.com/eyenoticeall/Lacuna/blob/main/LICENSE).
Artifacts published before the MIT-only change retain the grants under which they were released;
see the [changelog](https://github.com/eyenoticeall/Lacuna/blob/main/CHANGELOG.md).

---

<div align="center">
  <img src="https://raw.githubusercontent.com/eyenoticeall/Lacuna/main/logos/lacuna-logo-icon.webp" alt="Lacuna mark" width="72" />
  <p><strong>Bring a signal or backtest. Lacuna will try to find the gaps in the evidence.</strong></p>
</div>
