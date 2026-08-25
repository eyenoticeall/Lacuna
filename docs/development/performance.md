# Performance architecture and benchmarking

**Status:** benchmark artifact version 2 covers public signal/audit workflows, the three native
kernels, and the v0.3 path-independent cost-stress surface. The measurements establish reproducible
baselines; no hardware-independent latency promise is claimed.

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

The implemented Criterion suite covers:

- grouped average-rank IC at 10,000 and 100,000 rows with deterministic ties;
- 200 bootstrap mean reductions over 1,000-observation samples;
- interval purging for 100,000 training and 1,000 test intervals.

Build or run it with:

```bash
cargo bench --bench kernels --no-run
cargo bench --bench kernels
```

Criterion is a development-only dependency of `lacuna-core`. The committed configuration uses ten
samples, a 250 ms warm-up, and a one-second measurement window so the suite remains practical while
still producing statistical timing evidence.

### Python end-to-end benchmarks

Measure the public call, including:

- adapter and schema validation;
- sorting/rechunking/materialization;
- boundary conversion;
- kernel time;
- result construction.

Run equivalent Polars, pandas, NumPy, and Arrow inputs where supported. A fast kernel cannot compensate for an accidental full-data copy at its boundary.

The implemented runner measures forward labels, reference/native IC, quantiles, turnover, decay,
reference/native bootstrap, reference/native interval purge, the complete `SignalStudy.audit`
workflow, a nine-point `costs.stress` grid, and the point-in-time `bias.asof_join` reference path. It
invokes public APIs so validation, data movement, result construction, scenario projection, output
checksums, and traced Python memory are included.

The cost benchmark currently supports the NumPy/Polars reference implementation. It does not imply
a native cost path: native/reference differential testing becomes mandatory if measurements later
justify one.

```bash
lacuna bench --tier smoke --out benchmark.json

# The repository script exposes the same service.
python benches/python/bench_signal.py --tier small --repetitions 5
```

Use `--no-native` to isolate reference paths. Output is canonical JSON on stdout unless `--out` is
given; existing artifacts require `--overwrite`.

### Study benchmarks

Complete workflow benchmarks measure shared scans and repeated analyses. They catch regressions caused by recomputing labels, collecting lazy input multiple times, or creating excessive Python objects.

## Dataset scales

Maintain deterministic generators for approximate scales:

| Tier | Rows | Typical use |
|---|---:|---|
| Smoke | 4 thousand | correctness and runner integration |
| Small | 100 thousand | local iteration and crossover behavior |
| Medium | 5 million | pull-request benchmark subset |
| Large | 50 million | scheduled CI or dedicated runner |
| XL | 250 million | release/performance hardware only |

Generators specify instruments, dates, group skew, missingness, ties, horizons, and label overlap. Save generator configuration rather than large proprietary data.

The CLI exposes smoke, small, and medium tiers. Large and XL runs require an explicit custom
`BenchmarkConfig` on dedicated hardware so they cannot be launched accidentally in an ordinary
developer loop.

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

The versioned Python artifact records resolved configuration, Python/NumPy/Polars/native versions,
platform identity, per-case min/median/max wall time, throughput with units, traced Python peak
bytes, process peak RSS when the operating system exposes it, and a SHA-256 checksum of nonvolatile
result evidence. The equivalence checksum excludes the backend selector and rounds finite floats to
12 significant digits, a tighter normalization than the declared native/reference tolerances.
`tracemalloc` does not attribute every native allocation; the artifact says so
explicitly rather than presenting it as total process memory.

Generated timestamps and timings are volatile. Checksums exclude result creation timestamps and
must remain stable across repetitions on the same method/backend. A checksum mismatch fails the
benchmark run because comparing timings for different evidence would be meaningless.

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
