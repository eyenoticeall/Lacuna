# Contributing to Lacuna

Lacuna welcomes focused issues, reference implementations, tests, documentation, and benchmark-backed improvements. The project is pre-alpha, so discuss major public APIs or architecture changes before investing in a large patch.

## Local setup

```bash
uv sync --group dev --group docs
uv run lacuna doctor
```

Run the complete local quality gate before opening a change:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

## Statistical contributions

A new analytical method should include:

- a written definition and explicit assumptions;
- a slow, legible reference implementation or analytically known fixtures;
- unit and property tests, including null and adversarial cases;
- a documented missing-value, degrees-of-freedom, and temporal policy;
- deterministic seeds for randomized methods;
- benchmark evidence before adding a native kernel;
- structured outputs whose source tables can support later rendering.

## Native contributions

Keep Python/Rust calls coarse-grained, avoid observation-by-observation crossings, release the interpreter lock during independent computation, and document every allocation or materialization required at the data boundary.

## Changes and commits

Keep changes reviewable and update `CHANGELOG.md` under **Unreleased** for user-visible behavior. Major architectural changes should be captured as a short decision record in the pull request or future ADR directory.

By contributing, you agree that your contribution may be distributed under the project's MIT OR Apache-2.0 dual license.
