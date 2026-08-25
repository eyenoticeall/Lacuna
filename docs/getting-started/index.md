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

## Continue into the architecture

The current package is deliberately small. Before implementing a target API from the technical specification, read:

1. [Architecture](../concepts/architecture.md) for ownership and dependency direction.
2. [Semantic data model](../concepts/data-model.md) for time, identity, and missing-data contracts.
3. [Engineering handbook](../development/index.md) for change workflows.
4. The relevant [subsystem guide](../subsystems/signal-labels.md) for algorithms and tests.

Code examples in subsystem pages are contracts until their status says they are implemented.
