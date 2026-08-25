# Testing statistical software

Lacuna's test strategy is layered because ordinary unit tests cannot establish statistical calibration, temporal correctness, interoperability, and performance simultaneously.

## Test classes

### Unit tests

Unit tests cover exact behavior on small fixtures:

- formulas with hand-computed outputs;
- configuration validation and precedence;
- schema and policy errors;
- empty, singleton, constant, tied, and non-finite inputs;
- serialization and finding state;
- interval boundary conventions.

Keep fixtures small enough for a reviewer to verify manually.

### Reference tests

Reference tests compare against an independent authority:

- analytically known values;
- published paper examples;
- trusted SciPy, NumPy, or R implementations;
- a deliberately slow implementation with different control flow;
- externally maintained fixtures with documented provenance.

Copying the optimized algorithm into a “reference” module is not independent validation.

### Property tests

Hypothesis tests invariants across generated inputs. Important properties include:

- Spearman IC invariance under strictly monotonic signal transforms;
- every valid observation belongs to exactly one quantile;
- higher non-negative path-independent costs never improve net P&L;
- purged train intervals never overlap test label intervals;
- a safe as-of join never selects `available_time > decision_time`;
- adapter normalization preserves row values and semantic identity;
- serialization round-trips supported JSON values;
- deterministic randomized methods repeat for the same seed.

Generate degenerate groups and missing data deliberately; do not filter them all out of the strategy.

### Statistical simulation tests

Simulation tests ask whether a procedure behaves correctly over many generated samples:

- zero-alpha null false-positive rate;
- known cross-sectional correlation recovery;
- IID versus AR(1) interval coverage;
- block-bootstrap coverage under dependence;
- planted regime concentration;
- planted look-ahead leakage detection;
- multiple-testing correction behavior as trial count grows.

These tests use fixed root seeds, bounded runtime, and tolerance bands derived from Monte Carlo uncertainty. They should not assert an exact stochastic value.

### Differential tests

Run reference and optimized/native implementations on the same deterministic fixtures. Compare:

- result values within justified tolerances;
- row/group ordering;
- missing-value behavior;
- warnings and sample counts;
- interval selections and generated indices.

Differential tests are mandatory for native kernels.

### Integration tests

Integration tests cover boundaries:

- PyO3 import and error translation;
- wheel install and `py.typed` inclusion;
- Polars/pandas/Arrow/NumPy equivalence;
- lazy versus eager execution;
- CLI exit codes and machine-readable output;
- Markdown/JSON/HTML renderers consuming the same result.

### Regression tests

Every fixed correctness bug gets the smallest failing fixture as a regression test. Persisted result schemas keep representative old-version fixtures.

### Robustness and lineage tests

The v0.2 gate additionally requires:

- hand-computed p-value adjustments and ordering invariants;
- canonical identity invariance plus ambiguous/credential-bearing input rejection;
- append-only failure, retry, correction, selection, reopen, and concurrent-identity fixtures;
- planted plateaus, isolated optima, boundaries, and failed neighbors;
- seeded perturbation reproduction, constraint rejection, and attempt-budget exhaustion;
- half-open/overlapping subperiod evidence and timestamped universe composition;
- strictly trailing regime thresholds, future-availability detection, small/unknown regimes, and
  planted outcome concentration;
- exact `0.2.x` public exports/signatures and preservation of the `0.1.x` compatibility subset.

### Trading-realism tests

The v0.3 gate additionally requires:

- hand-computed commission, observed/assumed spread, slippage, impact, and borrow fixtures;
- property tests for non-negative cost monotonicity, side symmetry, zero-size identity, component
  reconciliation, and nonlinear impact growth;
- explicit failures for invalid units/signs, component duplication, currency mismatch, and likely
  double application;
- planted break-even roots, no-crossing evidence, monotonicity checks, and tolerance behavior;
- future/missing liquidity and borrow evidence that stays unknown rather than becoming zero;
- planted capacity erosion and participation-constraint breaches across multiple capital points;
- eager/lazy Polars, pandas, and Arrow equivalence;
- exact `0.3.x` public exports/signatures plus preservation of the `0.1.x` and `0.2.x` subsets;
- a deterministic end-to-end stress benchmark with output checksum and memory evidence.

### Data-correctness tests

The v0.4 gate additionally requires:

- exact and strict availability boundaries, one-nanosecond future rejection, staleness, and
  timezone-aware ordering;
- deterministic revision ties, unique version identities, monotone publication order, and explicit
  latest-only/unknown states;
- a planted delisted instrument, safe/biased/unknown source declarations, invalid and overlapping
  half-open intervals, and late or missing membership availability;
- future-known active-membership exclusion and selection invariance under input permutation;
- planted universe additions/removals with hand-computed retention, Jaccard similarity, and drift;
- dataset fixtures combining missing fields, nulls, duplicate keys, non-finite values, dtype defects,
  and temporal-order failures;
- eager/lazy Polars, pandas, and Arrow as-of equivalence;
- exact `0.4.x` public exports/signatures plus preservation of the `0.1.x` through `0.3.x` subsets;
- a deterministic end-to-end as-of benchmark with output checksum and memory evidence.

### Advanced-inference tests

The v0.5 gate additionally requires:

- exhaustive small CPCV combination fixtures, generated full-path coverage, and no retained label
  overlap after combinatorial purging;
- explicit embargo-after-each-test-group cases and combinatorial safety-limit failures;
- deterministic unrestricted, stratified, block, and sign-flip transformation streams;
- fixed-seed permutation null-size simulation and exchangeability warnings;
- direct PSR standard-error and MinTRL equations, zero-variance rejection, and DSR trial-family
  completeness including the selected Sharpe;
- CSCV reference combinations with visible selected strategy, OOS rank, relative rank, logit, tie
  behavior, and partition sensitivity;
- planted persistent-edge and forced-selection-overfit PBO simulations;
- one shared stationary-bootstrap index path across every strategy column;
- an independent literal White Reality Check distribution and finite-corrected p-value;
- an independent direct-lag Hansen stationary-bootstrap variance plus lower, consistent, and upper
  SPA recentering distributions;
- fixed-seed Reality Check/SPA null-size and planted-power simulations, including irrelevant poor
  high-variance alternatives;
- exact `0.5.x` public exports/signatures plus preservation of every `0.1.x` through `0.4.x` subset;
- deterministic benchmark artifact v4 cases and a clean-wheel advanced-inference smoke path.

### Fuzzing

Fuzz Rust interval logic, schema conversion, Arrow buffer handling, and parsers. Seed corpora include empty arrays, maximum offsets, malformed intervals, all-null buffers, dictionaries, and extreme finite floats.

## Numerical assertions

Choose tolerances from the algorithm and scale:

- exact equality for IDs, counts, indices, enums, and deterministic integer decisions;
- absolute tolerance near zero;
- relative tolerance for scaled nonzero statistics;
- combined tolerance where both regimes occur;
- distributional bands for simulations.

Document unusually loose tolerances. Never round both sides merely to make a test pass.

## Temporal fixtures

Temporal test data should visibly include:

- train labels that end exactly at test start;
- intervals crossing a test boundary;
- timezone transitions and daylight-saving changes;
- filings published after market close;
- revisions available at different historical times;
- delistings and changing universe membership;
- overlapping horizons.

Use explicit interval notation in test names or comments so closure semantics are reviewable.

## Randomness

Tests record a root seed. Production algorithms derive per-replicate streams independently of scheduling. A failure should print or retain enough information to reproduce the generated example.

Do not use wall-clock time, process ID, Python hash randomization, or thread scheduling as an implicit seed.

## Backend matrix

Where multiple execution paths exist, exercise:

| Dimension | Cases |
|---|---|
| Backend | reference, Polars/NumPy, native |
| Input | Polars eager/lazy, NumPy, optional pandas/Arrow |
| Python | minimum, primary development, newest supported |
| Platform | Linux, macOS, Windows wheel targets |
| Threads | 1 and representative parallel count |
| Size | boundary-small and benchmark-scale |

Not every pull request runs every large case. Scheduled CI owns expensive simulation and benchmark suites.

## Test markers

As suites grow, use explicit markers such as:

- `slow` for tests unsuitable for the default local loop;
- `statistical` for Monte Carlo calibration;
- `native` for compiled-extension requirements;
- `optional` for extra dependency matrices;
- `benchmark` for non-correctness performance runs.

Default CI must still cover all public behavior on representative small fixtures.

## Definition of tested

A method is not “tested” because one happy-path example passes. It needs evidence for the formula, invariants, edge policies, temporal semantics, serialization, supported adapters, and any optimized path.
