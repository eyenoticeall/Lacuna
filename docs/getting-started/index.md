# Getting started

## Requirements

- Python 3.11 or newer
- a stable Rust toolchain with Cargo
- uv

## Set up the repository

```bash
uv sync --group dev
uv run lacuna doctor
```

`uv sync` builds the mixed Python/Rust package in the local environment. The doctor command confirms that the compiled extension is importable and shows the active thread, seed, memory, cache, and logging configuration.

## Run quality checks

```bash
uv run ruff check .
uv run mypy
uv run pytest
cargo test --workspace
```

## Configuration

Use a scope when a setting belongs to one study:

```python
import lacuna as lc

with lc.config(threads=8, seed=42):
    current = lc.get_config()
```

The initial environment variables are `LACUNA_NUM_THREADS`, `LACUNA_MEMORY_LIMIT`, `LACUNA_CACHE_DIR`, and `LACUNA_LOG`.
