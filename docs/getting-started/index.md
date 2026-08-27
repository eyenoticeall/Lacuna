# Getting started

Lacuna is published on PyPI as `lacuna-quant`. The installed Python package and command remain
`lacuna`.

## Requirements

- Python 3.11 or newer
- `pip` or another Python package installer

Stable-ABI wheels are published for Linux x86-64 and arm64, macOS arm64, and Windows x86-64.
Other platforms require an explicit source build with a Rust toolchain.

## Install the current release

Install the core distribution and run its non-invasive installation diagnostics:

```bash
python -m pip install lacuna-quant
lacuna doctor --strict
```

The doctor checks package/native identity, distribution-name collisions, Python and wheel support,
dependency metadata, packaged schemas, and runtime configuration. Every result has a stable code
and actionable message. Use `lacuna doctor --json --strict` in automation.

Install optional method families through extras, and add the independently versioned options
extension only when needed:

```bash
python -m pip install "lacuna-quant[statistics,report,pandas]"
python -m pip install lacuna-options
```

The current releases are [`lacuna-quant` 0.13.0](https://pypi.org/project/lacuna-quant/) and
[`lacuna-options` 0.2.0](https://pypi.org/project/lacuna-options/). The same checksummed,
provenance-attested files are attached to the
[`v0.13.0` GitHub release](https://github.com/eyenoticeall/Lacuna/releases/tag/v0.13.0).

!!! warning "Distribution name"

    Do not install the PyPI project named `lacuna`; it is unrelated. If you used a historical
    Lacuna GitHub wheel whose distribution metadata was `lacuna`, remove it before installing from
    PyPI so two distributions do not own the same import path:

    ```bash
    python -m pip uninstall lacuna lacuna-options
    python -m pip install --upgrade lacuna-quant
    ```

    Reinstall `lacuna-options` afterward only if your research uses the extension.

## Run a signal audit

Given a signal table with `time`, `instrument`, and `signal` columns and a price table with `time`,
`instrument`, and `close` columns:

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

ic_result = study.ic()
quantile_result = study.quantiles()
report = study.audit(bootstrap_resamples=10_000, seed=42)
report.to_html("lacuna-audit.html")
```

Forward horizons are trading-observation counts, not calendar days. Unknown price adjustment,
delisting, survivorship, trial-history, or purged-validation evidence remains visible as `UNKNOWN`;
it is never silently treated as a pass.

The same workflow is available for local Parquet, CSV, Arrow IPC, or Feather files:

```bash
lacuna signal \
  --signal factor.parquet \
  --prices prices.parquet \
  --horizon 1D \
  --horizon 5D \
  --horizon 20D \
  --signal-observed-at open \
  --entry current_close \
  --price-adjustment total_return_adjusted \
  --bootstrap-resamples 10000 \
  --seed 42 \
  --out lacuna-audit.html
```

Use `--format json` without `--out` for clean machine-readable stdout. Reports use exclusive file
creation unless `--overwrite` is explicit. See the
[Alphalens migration guide](alphalens-migration.md) when converting an existing factor workflow.

## Configuration

Use a scope when a setting belongs to one study:

```python
import lacuna as lc

with lc.config(threads=8, seed=42):
    current = lc.get_config()
```

The initial environment variables are `LACUNA_NUM_THREADS`, `LACUNA_MEMORY_LIMIT`,
`LACUNA_CACHE_DIR`, and `LACUNA_LOG`.

## Develop from source

Repository development additionally requires a stable Rust toolchain, Cargo, and
[uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/eyenoticeall/Lacuna.git
cd Lacuna
uv sync --group dev --group docs --extra pandas --extra statistics --extra report
uv run lacuna doctor --strict
```

`uv sync` builds the mixed Python/Rust package in the local environment. Prefix installed commands
with `uv run` only when working inside this repository environment.

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

## Continue into the architecture

Before extending a released API or implementing a later contract, read:

1. [Architecture](../concepts/architecture.md) for ownership and dependency direction.
2. [Semantic data model](../concepts/data-model.md) for time, identity, and missing-data contracts.
3. [Engineering handbook](../development/index.md) for change workflows.
4. The relevant [subsystem guide](../subsystems/signal-labels.md) for algorithms and tests.

Subsystem status blocks distinguish implemented APIs from later contracts.
