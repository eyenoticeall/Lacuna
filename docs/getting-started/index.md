# Getting started

## Requirements

- Python 3.11 or newer
- a stable Rust toolchain with Cargo
- uv

## Set up the repository

```bash
uv sync --group dev --group docs
uv run lacuna doctor
```

`uv sync` builds the mixed Python/Rust package in the local environment. The doctor command confirms that the compiled extension is importable and shows the active thread, seed, memory, cache, and logging configuration.

## Run quality checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
uv run mkdocs build --strict
```

## Configuration

Use a scope when a setting belongs to one study:

```python
import lacuna as lc

with lc.config(threads=8, seed=42):
    current = lc.get_config()
```

The initial environment variables are `LACUNA_NUM_THREADS`, `LACUNA_MEMORY_LIMIT`, `LACUNA_CACHE_DIR`, and `LACUNA_LOG`.

## Run a signal audit

For a signal table with `time`, `instrument`, and `signal` columns and a price table with `time`,
`instrument`, and `close` columns:

```python
import lacuna as lc

study = lc.SignalStudy(
    signal=signal,
    prices=prices,
    horizons=("1D", "5D", "20D"),
    price_adjustment="total_return_adjusted",
    quantiles=5,
)

ic_result = study.ic()
quantile_result = study.quantiles()
report = study.audit(bootstrap_resamples=10_000, seed=42)
report.to_html("lacuna-audit.html")
```

Forward horizons are trading-observation counts, not calendar days. Unknown price adjustment,
delisting, survivorship, trial-history, or purged-validation evidence remains visible as `UNKNOWN`.
It is never silently treated as a pass.

The same workflow is available for local files:

```bash
uv run lacuna signal \
  --signal factor.parquet \
  --prices prices.parquet \
  --horizon 1D \
  --horizon 5D \
  --horizon 20D \
  --price-adjustment total_return_adjusted \
  --bootstrap-resamples 10000 \
  --seed 42 \
  --out lacuna-audit.html
```

Use `--format json` without `--out` for clean machine-readable stdout. Reports use exclusive file
creation unless `--overwrite` is explicit.

## Continue into the architecture

Before extending the implemented v0.1 path or implementing a later target API, read:

1. [Architecture](../concepts/architecture.md) for ownership and dependency direction.
2. [Semantic data model](../concepts/data-model.md) for time, identity, and missing-data contracts.
3. [Engineering handbook](../development/index.md) for change workflows.
4. The relevant [subsystem guide](../subsystems/signal-labels.md) for algorithms and tests.

Subsystem status blocks distinguish implemented APIs from later contracts.
