# Performance architecture and benchmarking

Performance is a product requirement, but only measured workloads justify optimization decisions.

## Non-negotiable rules

1. No Python loop whose iterations scale with observations in a core analysis path.
2. Cross the Python/Rust boundary at coarse granularity.
3. Preserve lazy or streaming execution until an algorithm truly needs materialization.
4. Favor columnar traversal and contiguous reductions.
5. Use `float64` by default; do not inflate or narrow dtypes accidentally.
6. Allocate output and scratch buffers deliberately.
7. Return batches, arrays, or tables rather than per-row Python objects.
8. Benchmark before and after any claimed optimization.

## Execution planner

The initial planner is explicit dispatch, not a general query optimizer:

| Workload | Preferred path |
|---|---|
| Small vectorized array | NumPy/reference |
| Lazy columnar projection/grouping | Polars |
| Large quant-specific repeated reduction | Rust |
| Mature statistical distribution/test | SciPy |
| Large Parquet scan | Polars streaming |
| Optional local SQL extraction | DuckDB Arrow stream |

Thresholds come from benchmark crossover points. They are versioned configuration or internal constants with benchmark references, not guesses embedded throughout code.

## Benchmark layers

### Rust microbenchmarks

Criterion benchmarks isolate kernels such as:

- grouped rank IC;
- quantile assignment;
- interval purging;
- dependent bootstrap;
- turnover;
- parameter-grid reductions.

Record input distribution, group sizes, null/tie characteristics, and thread count. A single uniformly random array is not representative of panel finance data.

### Python end-to-end benchmarks

Measure the public call, including:

- adapter and schema validation;
- sorting/rechunking/materialization;
- boundary conversion;
- kernel time;
- result construction.

Run equivalent Polars, pandas, NumPy, and Arrow inputs where supported. A fast kernel cannot compensate for an accidental full-data copy at its boundary.

### Study benchmarks

Complete workflow benchmarks measure shared scans and repeated analyses. They catch regressions caused by recomputing labels, collecting lazy input multiple times, or creating excessive Python objects.

## Dataset scales

Maintain deterministic generators for approximate scales:

| Tier | Rows | Typical use |
|---|---:|---|
| Small | 100 thousand | local iteration and crossover behavior |
| Medium | 5 million | pull-request benchmark subset |
| Large | 50 million | scheduled CI or dedicated runner |
| XL | 250 million | release/performance hardware only |

Generators specify instruments, dates, group skew, missingness, ties, horizons, and label overlap. Save generator configuration rather than large proprietary data.

## Measurements

Track:

- wall and CPU time;
- throughput in rows or resamples per second;
- peak RSS;
- allocations and bytes allocated where available;
- conversion/copy volume;
- thread count and CPU model;
- library/compiler build profile;
- output equivalence checksum.

Report warm and cold behavior separately when caches or dynamic loading matter.

## Regression policy

For stable benchmark cases, a greater than roughly 10% regression in throughput or peak memory requires investigation and an explicit explanation. Statistical benchmark tooling must account for noise before failing CI.

An accepted regression may be appropriate for correctness, stronger validation, or clearer semantics, but it is documented rather than hidden.

## Memory architecture

Prefer:

- streaming group accumulators;
- dictionary-encoded IDs;
- offsets rather than repeated group objects;
- reusable scratch buffers;
- bounded batches of bootstrap replicates;
- one projection of required columns before collection.

Avoid:

- materializing unused columns;
- duplicating an entire frame for naming convenience;
- converting to Python lists;
- allocating an `observations × resamples` matrix when a streamed reduction suffices;
- returning one Python object per group or row.

## Thread budget

Polars, Rayon, and BLAS may each own a thread pool. Lacuna exposes one effective budget and documents how it maps to backends. Nested workloads disable or cap inner parallelism to avoid oversubscription.

Benchmark both single-thread correctness baselines and parallel scaling. More threads are not assumed to be faster for small groups or memory-bound scans.

## Profiling workflow

1. Reproduce an end-to-end workload.
2. Capture a baseline with output checksum and memory.
3. Profile before changing code.
4. Identify computation, conversion, allocation, or scheduling cost.
5. Make the smallest architectural improvement.
6. Re-run correctness and differential tests.
7. Compare the same benchmark environment.
8. Document the crossover and tradeoff.

Do not merge an optimization whose only evidence is that the implementation “looks faster.”
