# Native core and PyO3 boundary

Rust is a performance implementation detail behind Lacuna's Python semantics. It owns measured quant-specific kernels, deterministic parallel work, allocation-sensitive loops, and language-independent correctness primitives.

## Workspace responsibilities

### `lacuna-core`

`lacuna-core` contains pure Rust algorithms and domain-neutral error types. It must not import Python, construct report objects, read environment variables, or decide user-facing column names.

Functions accept explicit buffers and configuration and return Rust values or compact structs. The crate is directly unit tested and benchmarked.

### `lacuna-python`

`lacuna-python` is a thin binding crate. It:

- extracts already normalized coarse-grained inputs;
- releases the interpreter lock for independent computation;
- calls `lacuna-core`;
- translates Rust errors into focused Python exceptions;
- returns arrays or compact structures, not millions of Python objects.

It does not own formulas, defaults, adapter logic, or provenance assembly.

## When a kernel belongs in Rust

All of these should be true or strongly evidenced:

- the operation is material in an end-to-end profile;
- its semantics have a tested reference implementation;
- it is quant-specific or awkward to express efficiently in a mature vectorized library;
- the call can process a large batch per boundary crossing;
- memory layout and allocation can be controlled;
- a benchmark shows a meaningful throughput, latency, or memory benefit.

Good candidates include grouped rank IC, dependent bootstrap, interval purging, combinatorial split generation, turnover, parameter-grid reductions, and temporal leakage scans.

Poor candidates include generic distribution functions, BLAS-heavy linear algebra, standard regressions, ordinary Polars joins, and tiny calls dominated by conversion overhead.

## Boundary shape

Bad:

```python
for row in rows:
    _native.process_row(row)
```

Good:

```python
_native.grouped_rank_ic(values, labels, group_offsets, config)
```

Native functions accept primitive arrays, Arrow-compatible buffers, offsets, and small serializable configuration. Python resolves dataframe column names before the call.

Return columnar arrays or compact summaries. If detailed row-level output is needed, return one contiguous buffer or table representation.

## Arrow integration

The long-term boundary is the Arrow C Data or C Stream interface where compatible. It is a trusted in-process pointer boundary.

An Arrow integration must:

- validate schema and buffer lengths before computation;
- keep producer-owned memory alive for the whole borrow;
- document buffer ownership and release callbacks;
- handle chunking explicitly;
- distinguish null bitmaps from NaN payloads;
- copy when alignment, mutability, sorting, or dtype conversion requires it;
- never claim zero-copy without measuring the actual path.

Unsafe code is isolated, documented with invariants, and fuzzed at schema/pointer boundaries.

## GIL and free-threaded Python

Release the interpreter lock during computation that does not touch Python objects. Move or borrow all required Rust-owned data before detaching.

The extension declares its GIL requirements accurately for supported free-threaded Python builds. Do not mark a module or class as free-thread safe until shared state and third-party calls are proven safe.

## Parallelism

Rayon is the default native parallelism candidate when benchmarks justify it. Parallel dimensions can include dates, resamples, parameter combinations, folds, regimes, universes, and horizons.

Rules:

- establish a minimum-work threshold;
- honor the effective Lacuna thread budget;
- avoid nested Rayon work;
- account for Polars and BLAS thread pools;
- make results deterministic across thread counts;
- batch reductions to avoid false sharing and excessive allocation.

## Deterministic randomness

Parallel randomized methods derive each replicate's stream from a stable root seed and replicate identity. Scheduling must not change the generated samples.

```text
root seed + method version
    ├── replicate 0 stream
    ├── replicate 1 stream
    └── replicate n stream
```

Record the root seed and RNG algorithm/version. Differential tests compare native and reference index generation on small fixtures.

## Numerical policy

- Default to `f64`.
- Reject or explicitly handle non-finite values.
- Use compensated or pairwise summation where cancellation is material.
- Define overflow, underflow, and empty-input behavior.
- Never use exact float equality in general numerical tests.
- Document tolerances with an error rationale, not arbitrary decimal places.

## Error design

Core errors identify the violated condition and relevant index or group. Binding translation preserves the message and selects a useful Python exception class.

Panics must not be a normal invalid-input path. Indexing, buffer shape, and interval assumptions are checked before unsafe or parallel loops.

## Test ladder

Every native kernel needs:

1. Rust unit tests for valid and invalid boundaries.
2. Python integration tests proving binding behavior.
3. Differential tests against an independent reference implementation.
4. Property tests for domain invariants.
5. Determinism tests across seeds and thread counts.
6. Benchmarks at small, medium, and large scales.
7. Memory/allocation evidence for claimed improvements.
8. Fuzzing when parsing schemas, intervals, or foreign buffers.

The Python reference remains available in tests even if production dispatch normally selects Rust.

## Build and packaging

maturin builds the mixed project from `rust/lacuna-python/Cargo.toml` and places the extension at `lacuna._native`. Keep Python and Cargo versions aligned for releases.

An ABI-stable wheel is a later evaluated decision. Do not enable `abi3` until required Python and Arrow integration paths are proven compatible.
