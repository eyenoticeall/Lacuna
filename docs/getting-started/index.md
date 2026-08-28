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

The current releases are
[`lacuna-quant` 0.14.0](https://pypi.org/project/lacuna-quant/0.14.0/) and
[`lacuna-options` 0.2.1](https://pypi.org/project/lacuna-options/0.2.1/). The same checksummed,
provenance-attested files are attached to the
[`v0.14.0` GitHub release](https://github.com/eyenoticeall/Lacuna/releases/tag/v0.14.0).

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

This complete example creates a small deterministic panel, computes signal diagnostics, assembles
an audit, and writes a core HTML report. It uses only dependencies installed with the core
distribution:

```python
from datetime import date, timedelta

import lacuna as lc
import polars as pl

instruments = ("A", "B", "C", "D", "E", "F")
calendar_days = tuple(date(2025, 1, 2) + timedelta(days=offset) for offset in range(50))
sessions = tuple(day for day in calendar_days if day.weekday() < 5)[:35]

prices = pl.DataFrame(
    {
        "time": [session for instrument in instruments for session in sessions],
        "instrument": [instrument for instrument in instruments for _ in sessions],
        "close": [
            100.0 + 4.0 * asset + day * (0.3 + 0.05 * asset) + 0.2 * ((day + asset) % 3)
            for asset, _instrument in enumerate(instruments)
            for day, _session in enumerate(sessions)
        ],
    }
)
signal = pl.DataFrame(
    {
        "time": [session for session in sessions for _ in instruments],
        "instrument": [instrument for _session in sessions for instrument in instruments],
        "signal": [
            float(((day + 2 * asset) % 11) - 5)
            for day, _session in enumerate(sessions)
            for asset, _instrument in enumerate(instruments)
        ],
    }
)

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
report = study.audit(bootstrap_resamples=200, seed=42)

print(ic_result.table("ic_by_horizon"))
print(quantile_result.table("quantile_returns"))
print(report.summary())
report.to_html("lacuna-audit.html")
```

The `time`, `instrument`, and value-column names are explicit public contracts. Forward horizons
are counts of successive observations per instrument, not calendar durations; Lacuna does not
infer a trading calendar from the synthetic dates. The example uses 200 bootstrap resamples so it
runs quickly. Use a research-appropriate resample count and validation design for substantive
analysis. Unknown delisting, survivorship, trial-history, or purged-validation evidence remains
visible as `UNKNOWN`; it is never silently treated as a pass.

The same executable workflow is maintained as
[`examples/quickstart.py`](https://github.com/eyenoticeall/Lacuna/blob/main/examples/quickstart.py).

Use the same workflow with local Parquet, CSV, Arrow IPC, or Feather files whose columns satisfy
the same contracts:

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
  --bootstrap-resamples 200 \
  --seed 42 \
  --out lacuna-audit.html \
  --bundle study.lacuna

lacuna bundle verify study.lacuna
```

Use `--format json` without `--out` for clean machine-readable stdout. Reports use exclusive file
creation unless `--overwrite` is explicit. Parquet and Arrow-family files preserve typed temporal
columns. The CSV scanner does not infer ISO date strings: encode `time` as a whole-number
observation index, or convert it to a Date/Datetime column before writing Parquet or Arrow IPC.
See the
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
