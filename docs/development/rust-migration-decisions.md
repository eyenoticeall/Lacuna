# v0.14 Rust migration decision ledger

**Status:** active implementation ledger for Lacuna 0.14.0.

This page records the operational outcome of every foundation and candidate in the
[Rust migration register](rust-migration-candidates.md). The register explains architecture and
candidate contracts; this ledger answers what was measured, what shipped, and why. A release tag
is blocked while any row remains `PROPOSED`, `MEASURED`, or `ADMITTED`.

## Evidence contract

Every measured row links to a `lacuna.native-migration-benchmark` version 1 artifact produced from
the exact source commit. The artifact records effective dimensions, reference and candidate
latencies, incremental process RSS, copy/workspace bytes, thread configuration, equivalence
checksums, and the admission decision. Generated inputs use fixed seeds and are created outside the
timed region. Native admission requires correctness plus one of:

- at least 1.5 times end-to-end throughput over the optimized reference;
- at least 30% lower incremental peak RSS with no more than 10% latency regression;
- bounded-memory completion of a declared workload the reference cannot complete under the same
  budget.

The result must reproduce in nightly CI and the non-publishing release preflight. A negative result
is terminal for v0.14 unless a changed design or new representative evidence is reviewed.

## Foundation decisions

| ID | State | Evidence commit/run | Effective shape | Reference/candidate result | Decision and reopening evidence |
|---|---|---|---|---|---|
| F-01 typed array boundary | MEASURED | `e4bbecd`; local same-wheel smoke | Python 3.11–3.14 on macOS arm64 | Typed NumPy bulk-copy boundary passed reference parity | Linux and target-wheel CI evidence is still required before release. |
| F-02a exact c14n-v1 streaming | OPTIMIZED_NON_NATIVE | [`c7fd033` array](../../benchmarks/native-migration/r16-array-c7fd033.json), [`c7fd033` frame](../../benchmarks/native-migration/r16-frame-c7fd033.json) | 100,000 × 4 float64 array and Polars frame | 12.83×/38.1% RSS and 1.58×/27.3% RSS; exact digests | Python streaming resolves the material allocation and latency problem. Reopen native work only with a different design and pinned-Linux evidence. |
| F-02b new identity | BLOCKED | ADR-017 | not applicable | Deferred | Reopen only through a new canonicalization ADR and migration. |
| F-03a compact internal carriers | PROPOSED | pending | cost, CV, and resampling projections | pending | Public projection cost must be included. |
| F-03b public carriers | BLOCKED | ADR-017 | not applicable | Deferred | Reopen through public API/schema migration. |
| F-04 execution budget | OPTIMIZED_NON_NATIVE | `2f5f180` | bounded bootstrap batches; native threads=1 | fixed/output and temporary allocation checks occur before allocation | Parallel native work remains blocked; extend the private resolver only as candidate callers migrate. |
| F-05 benchmark evidence | OPTIMIZED_NON_NATIVE | `f87dd72`, `c7fd033` | isolated smoke/small/medium cases | sidecar v1, alternating order, RSS and one untimed instrumented pass | Nightly and preflight must provide authoritative Linux run URLs. |

## Candidate decisions

| ID | State | Public operation | Evidence commit/run | Effective shape | Baseline / optimized / native | Correctness | Decision and reopening evidence |
|---|---|---|---|---|---|---|---|
| R-01 | ADMITTED | grouped rank IC | `e4bbecd`; local development run | 100,000 rows, 200 uniform groups | 282.50 ms / unchanged / 41.14 ms native (6.87×) | exact benchmark checksum plus analytical/differential boundary tests | Provisional admission. It is not `SHIPPED_NATIVE` until skewed-group Linux nightly, same-wheel ABI, and preflight evidence reproduce the gate. |
| R-02 | PROPOSED | cost stress | pending | `N`, `S`, periods, components | pending | pending | Optimize algebra before a fused reducer. |
| R-03 | PROPOSED | capacity curve | pending | `N`, `S`, `C`, periods | pending | pending | Apply exact scaling algebra first. |
| R-04 | PROPOSED | break-even cost | pending | periods and solver points | pending | pending | Preaggregate before reconsidering Rust. |
| R-05 | PROPOSED | purged/CPCV assembly | pending | `N`, `G`, `K`, overlap density | pending | pending | Include legacy projection cost. |
| R-06 | PROPOSED | shared resampling reduction | pending | `N`, `R`, `M`, block length | pending | pending | NumPy owns exact RNG streams. |
| R-07 | PROPOSED | permutation reduction | pending | `N`, `R`, strata | pending | pending | Depends on R-06. |
| R-08 | PROPOSED | PBO/CSCV | pending | `N`, `M`, `K` | pending | pending | Built-in statistics only. |
| R-09 | PROPOSED | bucket assignment | pending | `N`, `G`, buckets, ties | pending | pending | One-plan Polars reference first. |
| R-10 | PROPOSED | membership turnover | pending | `N`, `G`, `L`, buckets | pending | pending | Encoded-ID self-join first. |
| R-11 | PROPOSED | prior-only regime quantiles | pending | `N`, `W`, missingness | pending | pending | Exact NumPy-linear quantiles only. |
| R-12 | PROPOSED | event windows | pending | price `N`, events, window | pending | pending | Polars range/as-of plan first. |
| R-13 | PROPOSED | event response | pending | clusters, events, `W`, `R` | pending | pending | Reuse R-06; no event RNG. |
| R-14 | PROPOSED | portfolio projection | pending | cohorts, groups, legs | pending | pending | Polars allocation first. |
| R-15 | PROPOSED | universe transitions | pending | snapshots, instruments, churn | pending | pending | Encoded-ID Polars baseline first. |
| R-16 | OPTIMIZED_NON_NATIVE | c14n-v1 fingerprint | [`c7fd033` array](../../benchmarks/native-migration/r16-array-c7fd033.json), [`c7fd033` frame](../../benchmarks/native-migration/r16-frame-c7fd033.json) | 100,000 × 4 float64 array and Polars frame | array: 1.163 s / 90.61 ms; frame: 2.619 s / 1.659 s; no native spike | exact c14n-v1 checksums, frozen corpus, property and chunk-layout parity | Streaming Python passed the admission thresholds, so Rust is not justified. Reopen only for a changed encoder design backed by new benchmark evidence. |

## Release closure

Before tagging 0.14.0, replace every `pending` field required by a measured decision with the exact
artifact/run and source commit. Release notes list `SHIPPED_NATIVE`, `OPTIMIZED_NON_NATIVE`,
`NOT_MIGRATING`, and `BLOCKED` outcomes separately; they do not describe an unmeasured candidate as
a delivered performance improvement.
