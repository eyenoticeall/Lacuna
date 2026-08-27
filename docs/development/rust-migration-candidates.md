# Rust migration candidate register

**Status:** planning inventory; listing a candidate does not approve an implementation.

**Reviewed against:** Lacuna 0.13.0 source and benchmark configuration on 2026-08-27.

**Public behavior:** this register changes no API, method, result, fingerprint, or backend behavior.

This register identifies computation that could reasonably move from Python to Rust, the work that
should remain in Python, and the evidence required before a migration begins. It complements the
[native-core contract](native-core.md) and the [performance guide](performance.md).

## Decision

Lacuna should expand its Rust implementation selectively. A broad rewrite would move policy and
well-optimized Polars, NumPy, SciPy, or BLAS work into a less appropriate owner without proving an
end-to-end benefit. The useful target is narrower:

- eliminate Python iteration that scales with observations, resamples, scenarios, or combinations;
- eliminate Python-list and per-row-object transfer at native boundaries;
- fuse quant-specific repeated reductions when their contract is stable;
- preserve Python ownership of validation, methodology, provenance, findings, and public results.

The first profiling and design-spike targets are the cost surface, complete purged/CPCV split
assembly, shared resampling, grouped bucket assignment, membership turnover, and trailing regime
quantiles. None is presumed to belong in Rust. Each target first receives an algorithmic,
Polars, or NumPy reference improvement and proceeds to a native spike only when the admission gate
below is satisfied.

## Vocabulary, evidence state, and priority

| Disposition | Meaning |
|---|---|
| **IMPLEMENTED_NATIVE** | A Rust kernel exists, but its boundary or surrounding orchestration may still need work. |
| **MIGRATE_AFTER_PROFILE** | The operation has a plausible coarse native contract and observation-scaled Python work. Implement only after the admission gate passes. |
| **POLARS_FIRST** | Express the operation with Polars or Arrow first. Consider Rust only if the equivalent columnar implementation remains material. |
| **BLOCKED_BY_CONTRACT** | A public result, fingerprint, RNG, or plugin contract must be resolved before native work can provide the intended benefit. |
| **KEEP_PYTHON** | Python is the correct owner, or mature native libraries already execute the expensive work. |

Disposition describes the expected owner. The separately tracked evidence state records what has
actually been demonstrated for the v0.14 milestone:

| Evidence state | Meaning |
|---|---|
| **PROPOSED** | Registered but not yet measured. |
| **MEASURED** | Baseline and public-call profile captured. |
| **ADMITTED** | A native spike passed correctness and performance gates; not yet release-ready. |
| **SHIPPED_NATIVE** | The admitted native path is integrated, documented, and release-ready. |
| **OPTIMIZED_NON_NATIVE** | Algorithmic, Polars, or NumPy work solved the material bottleneck. |
| **NOT_MIGRATING** | Native work failed admission or is not material after reference optimization. |
| **BLOCKED** | A prerequisite such as ABI or compatibility proof failed. |

`ADMITTED` is not terminal. Before a v0.14 tag, every foundation and candidate is recorded as
`SHIPPED_NATIVE`, `OPTIMIZED_NON_NATIVE`, `NOT_MIGRATING`, or `BLOCKED` in the
[v0.14 migration decision ledger](rust-migration-decisions.md). A negative decision is closed for
the milestone and requires a changed design or new evidence to reopen.

Priorities describe investigation order, not release commitments:

| Priority | Meaning |
|---|---|
| **P0** | Cross-cutting prerequisite for honest native performance. |
| **P1** | Highest-value candidate for representative profiling and a design spike. |
| **P2** | Conditional candidate after P0/P1 work or after a Polars/algorithmic attempt. |
| **P3** | Do not schedule as a Rust migration without new evidence. |

Benefit and risk labels in the candidate matrix are comparative routing aids:

| Label | Expected benefit | Semantic risk | Packaging risk |
|---|---|---|---|
| **Low** | Unlikely to change a representative public call materially | Small, local equivalence surface | No native dependency or wheel change |
| **Medium** | Material only for particular shapes or workloads | Several edge policies or result projections | Existing native surface changes but no platform strategy change |
| **High** | Plausibly dominant latency, memory, or asymptotic behavior | RNG, temporal, identity, or broad public-result invariants | New FFI dependency, ABI, MSRV, or wheel-matrix exposure |

## Audited baseline

The current native core is deliberately small:

| Area | Current state | Consequence |
|---|---|---|
| `lacuna-core` | Exports `checked_mean`, `grouped_rank_ic`, `bootstrap_means`, and `interval_purge`. | Only rank IC, mean bootstrap reduction, and interval overlap participate in analytical paths. |
| `lacuna-python` | PyO3 functions accept and return Rust `Vec` values. They detach from Python during computation. | Inputs have already been copied/extracted before the GIL-free kernel begins; outputs become Python sequences. |
| Python callers | Native IC and bootstrap paths call `.to_list()` or `.tolist()`; CV constructs Python index lists around the overlap mask. | Kernel timing understates boundary and orchestration cost. |
| Parallelism | The Rust workspace has no Rayon dependency and the current kernels are single-threaded. | The configured Lacuna thread budget does not yet govern native work. |
| Benchmark CI | Pull requests compare the small 100,000-row tier with `--no-native`. | CI catches reference regressions but neither native regressions nor native/reference crossover changes. |
| Larger tiers | The runner defines a 5-million-row medium tier, but CI does not schedule it. Several cases cap their effective shape. | Nominal tier size does not prove that every combinatorial or event workload was tested at that scale. |
| Resource configuration | `threads` and `memory_limit` are resolved and recorded, but analytical execution does not enforce them. | A future native implementation cannot yet claim shared thread or memory-budget compliance. |

The committed initial integrated profile is useful routing evidence: in the smoke, reference-only
workflow, `costs.stress` accounted for about 78% of instrumented cumulative time and
`bias.asof_join` about 16%. That does not make the as-of join a Rust candidate. The join itself is
a Polars operation, while canonicalization and result construction can dominate an instrumented
path. The profile must be decomposed into computation, conversion, fingerprinting, and evidence
construction before choosing an owner.

### Scaling symbols

The rest of this page uses:

| Symbol | Dimension |
|---|---|
| `N` | observations or trades |
| `G` | groups, periods, or strata |
| `R` | resamples or permutations |
| `S` | cost scenarios |
| `C` | capital points |
| `K` | folds or enumerated combinations |
| `M` | strategies or model variants |
| `E` | events |
| `W` | event-window or rolling-window width |
| `L` | turnover lags |

## Native admission gate

A candidate enters implementation only when all of these are true:

1. Its estimand, eligibility, ordering, missing-data behavior, numerical behavior, and failure
   modes are already executable in a legible reference path.
2. A public-call profile at a representative shape attributes material time, memory, allocation, or
   unbounded scaling to the candidate rather than to unrelated validation or presentation.
3. The proposed call is coarse grained and accepts typed buffers, offsets, bitmaps, or Arrow data;
   it does not accept one Python object per observation.
4. The proposed output is compact enough that Python result construction does not recreate the
   eliminated allocation.
5. The benchmark includes normalization, transfer, kernel work, output conversion, fingerprinting,
   and result construction.
6. Native and reference results agree under the method's declared tolerances, with identical
   findings, warnings, eligibility counts, and equivalence checksums.
7. The reference fallback, backend selection, native-unavailable behavior, thread use, and peak
   memory are explicit and testable.

As a planning threshold, prefer a migration that demonstrates at least one of the following on the
first representative tier where the reference path is material:

- at least 1.5 times end-to-end throughput;
- at least a 30% peak-RSS reduction without more than a 10% latency regression;
- bounded-memory execution for a supported workload that the reference path cannot complete within
  its declared memory budget.

These are routing thresholds, not public performance promises. Use multiple same-runner
measurements, preserve the benchmark artifact, and document an exception when correctness or a
necessary boundary change justifies work before a threshold is met.

## P0 foundations

These items determine whether later Rust work produces a real user-visible benefit.

### F-01: typed buffer and Arrow boundary

**Disposition:** P0, **MIGRATE_AFTER_PROFILE**.

Replace analytical `Vec` extraction from Python lists with one or both of:

- borrowed typed contiguous buffers for normalized NumPy-compatible arrays;
- Arrow C Data or C Stream inputs for columnar, nullable, and chunked data.

The binding must validate dtype, length, offsets, null bitmaps, contiguity, alignment, and lifetime
before detaching from Python. It must return arrays, bitmaps, offsets, or an Arrow-compatible table,
not a list of Python scalars. A copy is acceptable when required by sorting, chunk consolidation, or
dtype normalization, but the copy must be measured and reported.

Apply this first to existing IC, bootstrap-mean, and interval-purge calls. It provides a clean
crossover measurement before adding more kernels.

### F-02a: byte-identical streaming c14n-v1 identity

**Disposition:** P0, **MIGRATE_AFTER_PROFILE**.

`frame_records()` currently turns a frame into Python dictionaries, and multiple analytical paths
then serialize those records for `fingerprint()`. At quant scale this can dominate both memory and
latency even when the analytical operation is already columnar.

A replacement first uses an incremental Python encoder over Polars/Arrow logical values. It may
avoid whole-frame dictionaries and lists, but must emit exactly the existing c14n-v1 byte stream.
Equivalent data must not acquire a different identity merely because chunk boundaries, dictionary
encoding, buffer offsets, or physical layout differ. The frozen compatibility corpus covers:

- column order and logical dtype encoding;
- row-order significance or the exact canonical sort;
- null versus NaN behavior;
- timezone, decimal, categorical, binary, and nested-value encoding;
- credential-shaped value rejection;
- stable framing so concatenated values cannot collide.

The existing `CANONICALIZATION_VERSION = 1` identity cannot change in place. Production callers
switch only after every frozen digest remains byte-identical and the end-to-end memory gate passes.
A Rust streaming encoder is considered only if exact Python streaming remains material.

### F-02b: new logical fingerprint identity

**Disposition:** P3, **BLOCKED_BY_CONTRACT**, deferred beyond v0.14.

Any intentional change to framing, canonical sort, scalar encoding, or physical/logical identity
requires a new canonicalization version, ADR, persisted-artifact migration, and explicit old-reader
behavior. It is not an optimization of c14n-v1 and must not be introduced under the v0.14
performance milestone.

### F-03a: compact internal result carriers

**Disposition:** P0, **MIGRATE_AFTER_PROFILE**.

Several candidates currently recreate `O(N)` Python objects after computation:

- cost components are tuples of Python floats or `None`;
- folds contain repeated tuples of train, test, purged, and embargoed indices;
- CPCV paths repeat index collections;
- some observation-level analytical tables are frozen JSON record tuples.

Use contiguous values plus validity bitmaps, and CSR-style data plus offsets, for internal
representation. Project immediately back to the unchanged v0.13 public result types and benchmark
that projection separately. Do not claim a memory improvement while the default return path still
materializes all legacy objects.

### F-03b: public compact result carriers

**Disposition:** P3, **BLOCKED_BY_CONTRACT**, deferred beyond v0.14.

Any public representation change requires API/schema review, compatibility fixtures, and a
separately approved migration. v0.14 preserves `Fold`, `CostEstimate`, evidence tables, and other
v0.13 public carriers exactly.

### F-04: effective execution budgets and dispatch

**Disposition:** P0 prerequisite; mostly **KEEP_PYTHON** orchestration.

Make the resolved memory limit operational and thread use observable. v0.14 native kernels are
single-threaded: this foundation blocks native parallelism, not independent single-thread kernels.
Define:

- the configured budget plus observed Polars and BLAS pools;
- minimum-work thresholds for native dispatch;
- bounded batch sizing for resampling and scenario work;
- behavior when an estimated allocation exceeds the limit;
- backend and thread-count provenance.

Python owns these decisions. Rust receives an already resolved budget and must not create an
independent pool. Rayon is not added in v0.14; `native_threads=1` is recorded explicitly rather
than implying that Lacuna controls third-party pools.

### F-05: representative native benchmark coverage

**Disposition:** P0 prerequisite; **KEEP_PYTHON** benchmark infrastructure.

Add native and reference cases at the same effective shape. The current 5-million-row tier still
caps interval input at 100,000 rows, strategy count at 12, and event instruments at 8; its bootstrap
sample length is tied to period count rather than panel rows. Those caps are useful safety controls,
but they must be named as separate shape dimensions rather than presented as full medium coverage.

## Candidate matrix

| ID | Public path or internal area | Disposition | Priority | Benefit | Semantic risk | Packaging risk | Evidence | Main prerequisite |
|---|---|---|---|---|---|---|---|---|
| R-01 | `signal.ic`, existing grouped rank IC | IMPLEMENTED_NATIVE | P1 | Medium | Medium | High | PROPOSED | F-01 |
| R-02 | Built-in cost estimates and `costs.stress`, `O(SN)` | MIGRATE_AFTER_PROFILE | P1 | High | High | Medium | PROPOSED | optimized algebra, F-01/F-03a |
| R-03 | `costs.capacity_curve`, currently up to `O(SCN)` | MIGRATE_AFTER_PROFILE | P1 | High | High | Medium | PROPOSED | scaling algebra, new benchmark |
| R-04 | `costs.break_even_cost` repeated reductions | POLARS_FIRST | P2 | Medium | Medium | Low | PROPOSED | period preaggregation |
| R-05 | Purged/CPCV split assembly, up to `O(KN)` | KEEP_PYTHON | P1 | High | High | Medium | OPTIMIZED_NON_NATIVE | F-01/F-03a |
| R-06 | Shared resampling reduction, `O(RN)`/`O(RNM)` | MIGRATE_AFTER_PROFILE | P1 | High | High | Medium | PROPOSED | F-01, Python-owned RNG |
| R-07 | Built-in permutation schemes/statistics | MIGRATE_AFTER_PROFILE | P2 | Medium | High | Medium | PROPOSED | R-06 |
| R-08 | PBO/CSCV combination evaluation, `O(KNM)` | MIGRATE_AFTER_PROFILE | P2 | Medium | High | Medium | PROPOSED | compact output, representative `M` |
| R-09 | Grouped bucket assignment | POLARS_FIRST | P1 | High | High | Medium | OPTIMIZED_NON_NATIVE | one-plan Polars reference |
| R-10 | Membership portion of turnover | POLARS_FIRST | P1 | Medium | High | Medium | PROPOSED | encoded IDs/self-join reference |
| R-11 | Prior-only expanding/rolling regime quantiles | MIGRATE_AFTER_PROFILE | P2 | Medium | High | Medium | PROPOSED | exact quantile reference, F-03a |
| R-12 | Event-window alignment/path extraction | POLARS_FIRST | P2 | Medium | High | Medium | PROPOSED | range/as-of reference |
| R-13 | Event-response cluster resampling | MIGRATE_AFTER_PROFILE | P2 | Medium | High | Medium | PROPOSED | R-06 |
| R-14 | Diagnostic portfolio allocation core | POLARS_FIRST | P2 | Medium | High | Medium | PROPOSED | columnar allocator reference |
| R-15 | Universe membership transitions | POLARS_FIRST | P2 | Medium | High | Medium | PROPOSED | encoded-ID self-join reference |
| R-16 | c14n-v1 semantic frame fingerprint | MIGRATE_AFTER_PROFILE | P0 | High | High | Low | PROPOSED | F-02a exact Python streaming |

### Audit coverage by subsystem

| Subsystem or source area | Routing decision |
|---|---|
| Frame/data boundary (`_frames.py`) | Typed analytical transfer is F-01; semantic identity is R-16/F-02a; schema validation, collection policy, and diagnostics remain Python/Polars. |
| Labels (`labels.py`) | Forward returns stay Polars. No Rust candidate. |
| Signal IC and decay (`signal.py`) | Existing Spearman kernel and its boundary are R-01; grouped Pearson and summary aggregation stay Polars/NumPy unless a later profile isolates a shared reducer; resampled decay support can reuse R-06. |
| Signal transforms (`_signal_transform.py`) | Bucket assignment is R-09; least-squares neutralization stays NumPy/BLAS with Polars-first group orchestration. |
| Turnover and projection (`signal.py`, `_portfolio.py`) | Membership churn is R-10; portfolio allocation is conditional R-14; rank, correlation, joins, and ordinary aggregations stay Polars. |
| Cross-validation (`cv.py`) | Existing overlap kernel plus complete split/path construction become R-05; configuration, time semantics, and public evidence stay Python. |
| Bootstrap/resampling (`validation.py`, `_resampling.py`) | Existing mean reducer and a shared deterministic engine become R-06; custom statistics stay Python. |
| Advanced inference (`_advanced_inference.py`) | Built-in permutation is R-07, PBO/CSCV is R-08, and Reality Check/SPA reuse R-06; Sharpe formulas, multiple-testing adjustments, and distribution calls stay NumPy/SciPy. |
| Costs and capacity (`costs.py`) | Built-in estimates/stress are R-02, capacity is R-03, and break-even is algorithm-first R-04. Liquidity diagnostics remain Polars/NumPy apart from R-16 identity work. |
| Point-in-time and bias (`bias.py`) | Joins and checks stay Polars; universe transitions are conditional R-15; record-based identity moves only under R-16. |
| Regimes (`regime.py`) | Expanding/rolling thresholds are R-11. Fixed, retrospective, and grouped regime summaries stay Python/NumPy/Polars. |
| Events (`events.py`) | Window alignment is Polars-first R-12; response inference reuses R-06 through R-13. |
| Robustness (`robustness.py`) | User-method and parameter-grid orchestration stays Python. No Rust candidate without a separately named built-in reducer. |
| Adapters (`adapters/`) | Container and metadata translation stays Python/Polars/Arrow. No Rust candidate. |
| Evidence, audit, persistence, and UI-facing services | `types.py`, `audit.py`, `audit_profiles.py`, `report.py`, `experiment.py`, `bundle.py`, `study.py`, `plugins.py`, `diagnostics.py`, `config.py`, and `cli.py` stay Python; only F-02a/F-03a supply lower-level compact data. |
| Options extension | Current chain analytics stay Polars/NumPy. No Rust candidate on present evidence. |

## Candidate designs

### R-01: finish the grouped rank-IC migration

**Current path.** Polars validates, joins, sorts, and identifies groups. Python constructs lists for
signal values, labels, and offsets before `grouped_rank_ic` runs. Rust implements average ties and
returns `None` for undersized or zero-variance groups.

**Proposed native boundary.**

- Input: borrowed `f64` signal/label buffers, validity information, and group offsets.
- Output: one `f64` result buffer plus a validity bitmap and optional per-group diagnostic code.
- Optional later work: parallel independent groups above a measured minimum-work threshold.

**Python retains.** Column selection, temporal join policy, null eligibility, sorting, method
selection, result rows, warnings, and backend provenance.

**Required equivalence.** Preserve average ties, signed-zero ties, finite-value policy, group
ordering, undefined groups, float tolerances, and deterministic results across thread counts.
Benchmark by both `N` and the group-size distribution; one large group and thousands of tiny
groups have different crossover points.

### R-02: fused built-in cost estimation and stress reduction

**Current path.** `costs.stress` constructs three Python tuples with one float per trade for every
scenario, merges base-component tuples, loops over every trade to handle unknown components, then
converts costs back to NumPy for period reductions. Built-in model estimates use similar
observation-level component tuples. The integrated reference profile already routes attention here.

**Proposed native boundary.**

- Input: normalized notional and gross-PnL buffers; optional period offsets; column-major base cost
  components with validity bitmaps; scenario coefficients; resolved annualization and capital.
- Output: per-scenario component totals, known/unknown counts, total/net PnL, optional return and
  Sharpe aggregates, plus compact status codes.
- Execute in bounded scenario batches and reuse scratch buffers.

**Python retains.** Trade schema and quantity conventions, observed-execution guards, currency,
scenario names and Cartesian policy, duplicate-component checks, model/plugin dispatch, findings,
warnings, fingerprints, and `AnalysisResult` construction.

Only built-in models and explicitly columnar model outputs qualify for the fast path. An arbitrary
Python `CostModel` remains supported through the reference protocol; Rust must not execute or
reinterpret a plugin. Missing components, all-known totals, period grouping, degrees of freedom,
and the exact half-spread convention require differential fixtures.

### R-03: capacity surface

**Current path.** Capacity evaluation repeats impact/cost calculations across scenario and capital
points and allocates several `N`-sized arrays for each point.

**Proposed native boundary.** Supply normalized trade buffers, period offsets, resolved built-in
impact parameters, scenario parameters, and capital points. Return a compact `S × C` metric
surface and diagnostic counts without returning per-trade modeled arrays.

**Python retains.** Model capability checks, capital grid validation, methodology, monotonicity and
warning policy, units/currency, and evidence assembly. Custom Python impact models stay on the
reference path.

Add an end-to-end benchmark before design work: vary `N`, `S`, `C`, period cardinality,
missing liquidity, and skewed notionals. Compare a fused native surface with an improved
allocation-reusing NumPy reference, not only with the current implementation.

### R-04: break-even evaluation

**Current path.** The solver evaluates 33 grid points and then bisects, creating full cost/net arrays
at each point. Net PnL and net return have algebraic simplifications; Sharpe and CAGR still require
period-level reductions.

First pre-aggregate notional and gross PnL by period and derive the linear metrics directly. Only
if the remaining Sharpe/CAGR solver is material should a native kernel evaluate a vector of cost
points against compact period aggregates. Python must keep bracketing, convergence, trace,
non-monotonicity, and error policy. Do not move a repeated `O(N)` algorithm into Rust when it can
first become `O(P)`, where `P` is the number of periods.

### R-05: whole purged and combinatorial split assembly

**Measured outcome.** The v0.14 NumPy reference precomputes chronological group and period codes,
uses vectorized half-open interval search, and eliminates repeated Polars filters. At 100,000 rows,
six groups, and 15 combinations it reduced the original 420.52 ms public call to 184.60 ms while
preserving the exact benchmark checksum.

The design spike evaluated this native boundary:

- Input: source-order period codes, half-open label-start/end buffers, fold/group boundaries,
  embargo count, and enumerated test-group combinations.
- Output: CSR-style concatenated train/test/purged/embargo index buffers with fold offsets; compact
  group-to-fold path incidence; per-fold counts and status codes.

Python retains time dtype validation, stable period encoding, split configuration, safety limits,
method/version metadata, and result/evidence policy.

The complete spike passed analytical, differential, adversarial, source-order, path-incidence, and
boundary tests. After optimizing compact-carrier validation and projection, its exact-commit
full-call median was 159.42 ms versus 184.60 ms for the optimized reference: only 1.158 times faster,
below the 1.5 times gate. The unchanged `Fold` tuples and evidence rows dominate the common path,
so the Rust kernel, PyO3 binding, carrier, and dispatch were removed. R-05 is
`OPTIMIZED_NON_NATIVE` for v0.14. Reopen it only with a changed projection design or new benchmark
evidence; a public carrier redesign remains deferred.

### R-06: shared deterministic resampling engine

**Current path.** Bootstrap paths allocate NumPy index arrays or Python lists for each replicate,
flatten batches, and convert them to lists for the existing mean reducer. Stationary-bootstrap
helpers allocate an `R × N` index matrix. Reality Check, SPA, and event inference have separate
replicate loops and repeated concatenation.

Use two explicit stages:

1. **Boundary stage:** preserve the existing NumPy-generated indices but pass typed buffers and
   offsets directly to native built-in reducers. This can improve transfer without changing random
   streams.
2. **Fused reducer stage:** consume bounded Python-generated replicate streams and reduce them in
   Rust, returning only the requested distribution or summary.

The shared engine should support built-in, validated reducers such as mean and joint column means
first. Median, Sharpe, studentization, and simultaneous-band primitives can be added only with their
own reference and benchmark. Arbitrary Python statistics remain Python and may still use bounded
index generation.

Python retains method selection, interval construction, statistical warnings, quantiles, findings,
provenance, and NumPy PCG64/SeedSequence index generation. Native RNG generation is excluded from
v0.14. Batch boundaries must not change the existing stream or replicate identity.

### R-07: permutation engine

Migrate only built-in reducers after R-06 establishes deterministic replicate identity and bounded
reduction. Python generates the existing permutation indices and supplies value buffers, optional
stratum offsets, and flattened indices; Rust may return the replicate distribution and diagnostic
counts.

Keep custom callables in Python. Preserve exact exchangeability units, block boundaries, stratum
membership, alternative-tail comparison, tie counting, and plus-one p-value behavior. Benchmark
high-cardinality strata as well as unstratified arrays.

### R-08: PBO/CSCV combination evaluation

**Current path.** The reference enumerates symmetric combinations, concatenates in-sample and
out-of-sample indices, slices an `N × M` matrix, evaluates strategies, and ranks the selected
strategy for every combination.

**Proposed native boundary.** Consume a contiguous returns matrix, partition offsets, enumerated
combination codes, and a built-in statistic identifier. Return selected strategy indices,
out-of-sample ranks/logits, and small per-combination metrics. Python retains strategy names,
combination safety limits, findings, distribution summaries, and evidence.

The current benchmark caps `M` at 12, so it is not admission evidence for a quant's broad strategy
search. Test ties, non-finite rejection, constant strategies, partition imbalance, memory layout,
and the explicit maximum-combination guard. Custom statistics stay on the reference path.

### R-09: grouped bucket and quantile assignment

**Measured outcome.** General bucket assignment now uses one Polars plan for group validation,
stable ordering, balanced and preserve-tie ranks, split-aware quantiles, equal-width and fixed-edge
assignment, thresholds, explicit drops, and attrition. The prior group-partitioned NumPy path is
retained as an independent test oracle.

First attempt a single equivalent Polars expression for the supported `BucketSpec` policies. If it
cannot preserve the exact tie, boundary, small-group, and out-of-range rules efficiently, use:

- input value buffers, group offsets, and a stable encoded instrument tie key;
- a serialized bucket specification and ascending flag;
- output `int32` assignments, validity bitmap, and group exclusion/status codes.

Python retains availability validation, stable entity encoding, undersized-group policy, findings,
attrition, output naming, and sorted frame construction. Differential tests must cover exact
boundary values, repeated values crossing requested quantiles, signed zero, nulls, group skew,
string/integer identifiers, stable ordering, and fewer effective buckets than requested.

At 100,000 rows, 200 groups, and five buckets, the exact public checksum was preserved while the
median fell from 142.19 ms to 61.87 ms (2.30 times faster) and traced Python peak memory fell by
about 17.6%. The remaining assignment work is columnar Polars, so no Rust spike is justified.
R-09 is `OPTIMIZED_NON_NATIVE`; reopen only if a new representative profile isolates a material
residual outside Polars. `signal.quantiles` reuses this assignment primitive, while return
aggregation remains Polars.

### R-10: membership turnover reducer

The rank-turnover and signal-autocorrelation portions are already expressed as Polars joins and
aggregations. The native candidate is only membership churn: the current path builds Python sets for
every period and bucket, then iterates over `L × G × B`.

Dictionary-encode instrument identities in Python/Polars, sort integer IDs by period and bucket,
and pass values plus offsets to a native intersection/symmetric-difference reducer. Return counts
and turnover values per lag/period/bucket. Preserve exact-lag behavior, absent versus empty buckets,
changing universes, denominator-zero behavior, stable time ordering, and top/bottom bucket
projection.

### R-11: exact prior-only trailing regime quantiles

Only the expanding and rolling modes are candidates. Fixed thresholds are constant work and the
retrospective mode uses one NumPy quantile calculation.

The current prior-only loop filters finite history and calls `np.quantile` at each observation.
For expanding mode this can approach quadratic work. A native implementation can maintain an exact
order-statistic structure for expanding history and a deletion-capable structure for a rolling
window.

The contract must reproduce NumPy's declared quantile interpolation, use history strictly before
the current observation, distinguish null/NaN/infinity, enforce `min_history`, and emit the exact
lower/upper threshold, history count, and label. The observation-level result currently becomes
JSON-style records, so F-03a must include the unchanged public projection in its measurement.

### R-12: event-window alignment and extraction

This is **POLARS_FIRST** because as-of alignment and range extraction are general temporal
operations. Build an equivalent sorted Polars plan using instrument keys and next-observation
semantics, then measure it against the current event loop.

If a residual quant-specific path remains material, a native kernel may consume sorted price
buffers, instrument/price offsets, event anchor buffers, price validity, and before/after widths.
It would return event-to-anchor row indices, path row indices, offsets, and censor/status codes.
Python retains anchor policy, availability/lookahead findings, corporate-action declaration,
overlap policy and clustering, attrition, and the `EventWindowResult`.

Test missing instruments, null anchor prices, duplicate-key rejection, left/right censoring,
irregular calendars, same-time events, high event concentration in one instrument, and exact
next-observation behavior.

### R-13: event-response resampling

Do not create an event-specific RNG or scheduler. Express complete paths as a contiguous response
matrix with anchor-cluster offsets and reuse R-06 to generate stationary cluster samples and reduce
pointwise means. Return the replicate-by-offset distribution or the sufficient data for pointwise
and simultaneous bands.

Python retains complete-path eligibility, minimum-cluster policy, descriptive results, confidence
construction, findings, and attrition. Tests must preserve cluster sampling rather than event-row
sampling, jointly resample every offset, and remain identical across thread counts.

### R-14 and R-15: conditional columnar candidates

`signal.portfolio_projection` should first replace Python cohort/group/leg iteration and
dictionary bookkeeping with Polars grouping, joins, and window expressions. Only a residual
quant-specific constrained allocator is a Rust candidate; BLAS-like or generic dataframe work is
not.

Universe drift and membership checks should first use encoded IDs plus Polars self-joins and grouped
set/count expressions. A native sorted-membership transition scan is reasonable only if snapshot
cardinality and churn remain material after that rewrite.

## Explicit non-candidates

The audit also records where Rust should not be introduced, preventing future profiling work from
repeating the ownership analysis.

| Area | Disposition and reason |
|---|---|
| `labels.forward_returns` | **KEEP_PYTHON/POLARS.** Sorting, grouped shifts, windows, and horizon projection are columnar; the Python loop scales with the small declared horizon count, not observations. |
| `bias.asof_join` and ordinary temporal joins | **KEEP_PYTHON/POLARS.** Polars owns sorting and as-of joins. Optimize F-02a fingerprinting and result conversion separately. |
| Future-data, revision, survivorship, membership, and dataset-bias checks | **KEEP_PYTHON/POLARS** unless the narrow R-15 transition scan passes admission. These are expressions and evidence policy, not bespoke numeric kernels. |
| `regime.regime_analysis` | **KEEP_PYTHON/NUMPY.** It reduces a small number of regimes; address observation-record identity separately. |
| `signal.neutralize` linear solves | **KEEP_PYTHON/NUMPY/BLAS.** Do not reimplement least-squares solvers. Group/design-matrix orchestration is Polars-first. |
| `signal.fit_decay` | **KEEP_PYTHON/SCIPY.** The constrained nonlinear optimizer remains SciPy. Shared native resampling may supply indices, but each fit keeps the authoritative optimizer. |
| Multiple-testing p-value adjustments | **KEEP_PYTHON/NUMPY.** Arrays are small relative to research data, and the formulas are already vectorized. |
| Robustness parameter, subperiod, continuous-parameter, and universe studies | **KEEP_PYTHON.** They orchestrate user functions, method registries, and evidence. Rust cannot call arbitrary Python methodology without reversing the dependency boundary. |
| Audit rules, standardized profiles, reports, result types, and attrition | **KEEP_PYTHON.** They own policy and presentation, and should operate over already computed evidence. |
| Experiment registry, bundles, canonical JSON, CLI, plugins, diagnostics, and configuration | **KEEP_PYTHON.** These are persistence, security, I/O, and orchestration. R-16 may accelerate only a separately versioned semantic frame hash. |
| Polars, pandas, Arrow, DuckDB, vendor, backtest, factor-panel, and scikit-learn adapters | **KEEP_PYTHON/POLARS/ARROW.** Adapters translate containers and metadata; they do not own analysis kernels. |
| `lacuna-options` chain validation, delta buckets, and empirical residuals | **KEEP_PYTHON/POLARS/NUMPY** at current evidence levels. No observation-scaled Python numeric bottleneck has been established. |
| Public initialization, versioning, exceptions, schemas, and native loading | **KEEP_PYTHON** except for the existing thin PyO3 bridge. |
| Arbitrary statistics, cost models, impact models, and other Python callables | **KEEP_PYTHON fallback.** A native fast path may support named built-ins but must not silently replace or execute a user callable. |

## Benchmark and evidence plan

### Current coverage gaps

Before accepting a migration claim:

- schedule or manually preserve a true medium-tier artifact; the current pull-request comparison is
  small and reference-only;
- add native and reference cases to the same artifact and compare equivalence checksums;
- report effective case dimensions separately from the top-level panel row count;
- remove hidden case caps for dedicated runs, or state the cap in the case name and configuration;
- measure process peak RSS and transfer/copy bytes in addition to traced Python memory;
- record effective Polars, Rayon, and BLAS thread counts.

### Required shapes

| Candidate | Shape dimensions | Adversarial axes | Primary measures |
|---|---|---|---|
| R-01 IC | `N, G`, group-size distribution | ties, signed zero, null density, chunking, group skew | total latency, transfer bytes, peak RSS |
| R-02 stress | `N, S`, period count, component count | null components, base models, skewed notional | scenario rows/s, allocations, peak RSS |
| R-03 capacity | `N, S, C` | missing liquidity, capital extremes, period skew | surface points/s, peak RSS |
| R-05 CV | `N, G, K`, interval density | long overlaps, touching bounds, embargo, unsorted source | folds/s, bytes per fold, result projection cost |
| R-06 resampling | `N, R, M`, block length | small/large blocks, seeds, non-divisible batches | sampled values/s, peak RSS, determinism |
| R-07 permutation | `N, R, G` | many tiny strata, ties, block boundaries | permutations/s, peak RSS |
| R-08 PBO | `N, M, K` | tied strategies, constant columns, combination limit | combinations/s, matrix-copy bytes |
| R-09 buckets | `N, G`, bucket count | high cardinality, ties, nulls, group skew | rows/s, group allocations |
| R-10 turnover | `N, G, L`, bucket count | universe churn, empty buckets, string IDs | membership comparisons/s, peak RSS |
| R-11 regimes | `N, W` | missing runs, repeated values, expanding versus rolling | rows/s, asymptotic slope, peak RSS |
| R-12 windows | price `N, E, W` | concentrated events, censoring, irregular times | output rows/s, allocation count |
| R-13 response | clusters, events, `W, R` | unequal cluster sizes, incomplete paths | path values/s, peak RSS |

Use at least smoke, 100,000-row small, 5-million-row medium, and a dedicated 50-million-row large
case where the workload is observation-scaled. Scale `R`, `S`, `C`, `K`, `M`, and `E`
independently; a large `N` with 12 strategies or eight event instruments does not establish the
other dimensions.

Every benchmark invocation must validate output before its timing is admitted. Preserve the
generator configuration, environment metadata, repetitions, raw measurements, checksum, and peak
memory. A single local timing is diagnostic, not migration evidence.

### CI progression

1. Keep a fast reference smoke/small correctness case on every pull request.
2. Add native/reference differential cases on wheel-enabled CI.
3. Run the full effective medium shape on a scheduled or dedicated runner until its variance and
   runtime are understood.
4. Run large cases on scheduled dedicated hardware.
5. Reserve XL cases for release/performance hardware and explicit operator intent.

## Compatibility and versioning

| Change | Required treatment |
|---|---|
| Equivalent backend with unchanged mathematical and result contract | Keep the method version; record `backend`, native version, dispatch reason, and material thread/RNG details in provenance. |
| Different RNG algorithm or random stream | Increment the affected method version, identify the RNG algorithm/version, and retain old-stream fixtures or a documented compatibility path. |
| New semantic frame fingerprint | Publish a new canonicalization/fingerprint version and persisted-identity compatibility rules; never rewrite old identities silently. |
| Different public result representation | Review the Python API and result schema, provide compatibility fixtures/projection, and version the schema or method where interpretation changes. |
| Different floating reduction order | Demonstrate agreement inside a declared method-specific tolerance and deterministic behavior for each supported thread count. If interpretation changes, version the method. |
| New native-only capability | Define native-unavailable behavior. Do not silently substitute a different method on reference-only installations. |

## Recommended sequence

### Phase 0: make measurements honest

1. Add F-05 case dimensions and native/reference coverage.
2. Implement F-01 for the three existing analytical kernels.
3. Design F-03a internal carriers for CV and cost components without changing public carriers.
4. Implement F-02a only as a byte-identical c14n-v1 stream; keep F-02b deferred.
5. Make F-04 budgets observable and enforceable.

### Phase 1: remove the largest repeated work

1. R-02 cost stress and built-in component reductions.
2. R-05 complete purged/CPCV split assembly.
3. R-06 shared resampling boundary, followed by a separately approved fused RNG/reducer.
4. R-03 capacity surface if its new benchmark passes admission.

### Phase 2: high-cardinality transforms

1. R-09 grouped bucket assignment after a Polars equivalence attempt.
2. R-10 membership turnover only.
3. R-11 expanding/rolling regime quantiles.

### Phase 3: conditional work

Evaluate R-07, R-08, and R-12 through R-15 only with representative profiles after shared
foundations exist. Do not schedule a native rewrite of joins, linear algebra, optimizers, adapters,
reporting, audit policy, persistence, or user-callback orchestration.

## Per-candidate definition of done

A candidate is complete only when:

- the reference implementation remains available as a differential oracle;
- the core Rust API is Python-independent and accepts checked coarse-grained buffers;
- the PyO3 layer contains conversion and exception mapping only;
- empty, null-heavy, non-contiguous, chunked, misaligned, and oversized inputs are covered;
- invalid dimensions, offsets, bitmaps, intervals, and integer conversions cannot panic;
- Python integration, property, differential, determinism, and packaging smoke tests pass;
- the public-call benchmark includes transfer, allocation, fingerprint, and result costs;
- medium-tier crossover and peak-memory evidence are preserved;
- thread and memory budgets are honored;
- findings, warnings, provenance, method versions, and output checksums match the declared contract;
- the subsystem, API, performance, release, and compatibility documentation is updated as needed.

Until those conditions hold, the item remains a candidate rather than an approved Rust migration.
