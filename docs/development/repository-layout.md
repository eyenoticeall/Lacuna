# Repository layout and dependency rules

## Current foundation

```text
.
├── python/lacuna/          Python package
│   ├── adapters/           edge-format normalization
│   ├── config.py           immutable runtime configuration
│   ├── labels.py           forward-return labels and intervals
│   ├── signal.py           IC, quantiles, turnover, and decay
│   ├── cv.py               walk-forward and purged folds
│   ├── validation.py       deterministic bootstrap inference
│   ├── experiment.py       canonical identities and append-only trial lineage
│   ├── robustness.py       perturbation, subperiod, and universe evidence
│   ├── regime.py           regime classification and conditional evidence
│   ├── costs.py            cost models, stress, liquidity, and capacity
│   ├── bias.py             point-in-time joins, revisions, and universe evidence
│   ├── audit.py            versioned rules and scoring
│   ├── report.py           JSON/Markdown/HTML presentation
│   ├── study.py            high-level signal workflow
│   ├── benchmark.py        reproducible public-path benchmarks
│   ├── types.py            result and finding foundation
│   └── native.py           native-extension inspection
├── rust/
│   ├── lacuna-core/        language-independent kernels
│   └── lacuna-python/      thin PyO3 bridge
├── tests/
│   ├── unit/
│   ├── property/
│   ├── reference/
│   ├── schema/
│   ├── golden/
│   └── integration/
├── schemas/                 versioned machine-readable result contracts
├── benches/
├── examples/
├── docs/
├── pyproject.toml
└── Cargo.toml
```

## Target Python packages

Add domain packages incrementally as real capabilities land:

```text
python/lacuna/
├── signal/
├── labels/
├── cv/
├── validation/
├── regime/
├── costs/
├── bias/
├── audit/
├── report/
├── adapters/
└── experiment/
```

An empty package tree creates false API expectations. A package is introduced with its first cohesive implementation, tests, exports, and documentation.

## Internal module pattern

A domain package should generally separate:

```text
domain/
├── __init__.py       curated public exports
├── _contracts.py     configuration, protocols, typed input/result fields
├── _normalize.py     domain-specific semantic validation
├── _reference.py     legible correctness implementation
├── _compute.py       execution dispatch and optimized paths
└── _version.py       method versions when more than one method exists
```

This is a pattern, not a mandatory file count. Keep small modules together until ownership or reviewability justifies a split.

## Import direction

Domain modules may depend on foundational types, configuration, adapters, and native wrappers. Foundation modules do not depend on a domain.

```text
config/types/exceptions
          ↑
       adapters
          ↑
 labels/signal/cv/validation/costs/bias
          ↑
        studies
          ↑
     audit/reporting
```

Avoid lateral imports between domains. If `signal` and `validation` need the same primitive, place it in a small neutral internal module only after the shared contract is clear. Do not create a miscellaneous `utils.py` dumping ground.

## Rust workspace growth

The workspace intentionally starts with `lacuna-core` and `lacuna-python`.

Split a new crate only when at least one condition is true:

- it has a stable, language-independent API boundary;
- separate compile or benchmark ownership materially helps;
- dependencies are meaningfully isolated;
- fuzzing or no-std/platform constraints differ;
- multiple bindings need the same crate.

Potential later crates such as `lacuna-signal`, `lacuna-resample`, or `lacuna-cv` are not roadmap checkboxes. Premature splitting increases compile time and cross-crate coordination.

## Dependency tiers

Core remains lean:

- NumPy;
- Polars;
- the compiled extension.

SciPy, reporting, pandas/PyArrow, ML, and DuckDB live behind extras. A domain module must not import an optional dependency at module import time unless the user invoked that feature. Missing extras raise a focused installation error naming the extra.

Before adding a mandatory dependency, document:

1. the capability it owns;
2. why the standard library, NumPy, Polars, or existing dependencies are insufficient;
3. wheel/platform consequences;
4. import-time and package-size impact;
5. license compatibility;
6. whether it can be optional.

## Public and private names

Public names are exported deliberately from package `__init__.py` files and included in typing and documentation. Internal modules and functions use a leading underscore.

Do not expose a native function directly merely because it exists. Python wrappers own input semantics, error translation, configuration, and result construction.

## Generated and local artifacts

Never commit:

- virtual environments;
- compiled extension binaries;
- `target/`, `dist/`, or built documentation;
- caches, coverage output, or benchmark scratch data;
- proprietary market data;
- local credentials or machine-specific configuration.

Commit lockfiles, type stubs, small deterministic fixtures, benchmark definitions, schema fixtures, and documentation source.

## Tests and fixtures

Tests are organized by purpose rather than by mirroring every source directory:

- `unit` for exact local behavior;
- `reference` for published or independent expected values;
- `property` for invariants;
- `statistical` for simulation calibration;
- `integration` for language and adapter boundaries;
- `regression` for fixed bugs and persisted schema compatibility;
- `golden` for byte-stable representative artifacts;
- `schema` for compatibility validation against published contracts.

Add directories when their first tests land. Large generated datasets belong in reproducible fixture builders or external benchmark storage, not Git.
