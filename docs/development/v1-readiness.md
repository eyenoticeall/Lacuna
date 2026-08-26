# v1 readiness ledger

This ledger maps the technical specification's `1.0.0` definition to released evidence and remaining
work. It prevents a long feature list from being mistaken for a stable product contract. Status is
evaluated in four states:

- **released** — the capability has a tagged public contract and release evidence;
- **hardening** — the capability exists, but cross-release or cross-subsystem evidence is incomplete;
- **missing** — the required internal contract is not implemented;
- **external** — completion depends on evidence the repository and CI cannot create.

## Definition ledger

| v1 definition item | Status after the `0.7` milestone | Evidence and remaining gate |
| --- | --- | --- |
| stable data-contract semantics | Hardening | Labels, adapters, point-in-time joins, dataset specs, and backtest schemas are released; `0.8` must reconcile their error/provenance behavior and `1.0` must make the stability declaration. |
| stable result schema | Hardening | `AnalysisResult` schema 1, JSON Schema, golden fixtures, and preserved API series exist; migration tests must exercise persisted `0.1`–`0.7` evidence before the v1 freeze. |
| mature signal diagnostics | Released | Forward labels, IC, quantiles, turnover, and multi-horizon decay shipped in `0.1`. |
| mature financial CV | Released | Walk-forward, purged K-fold, embargo, and CPCV/path evidence shipped through `0.5`. |
| robust bootstrap/permutation | Released | IID and dependent bootstrap plus explicit permutation nulls and deterministic streams shipped through `0.5`. |
| PSR/DSR | Released | Sharpe uncertainty, PSR, DSR, and minimum track-record evidence shipped in `0.5`. |
| multiple-testing support | Released | Bonferroni, Holm, BH, BY, PBO, Reality Check, and SPA are public with family-completeness contracts. |
| parameter stability | Released | Parameter surfaces, continuous perturbation, subperiods, and universe perturbation shipped in `0.2`. |
| regime analysis | Released | Fixed, trailing point-in-time, and explicitly retrospective regimes plus conditional evidence shipped in `0.2`. |
| cost stress | Released | Composable costs, stress scenarios, break-even, liquidity, and capacity evidence shipped in `0.3`. |
| point-in-time checks | Released | Availability-safe joins, revisions, future-data checks, survivorship, membership, drift, and dataset validation shipped in `0.4`. |
| standardized audit | Hardening | The versioned rule engine is stable, but the default audit is still centered on the original signal workflow. `0.8` must compose robustness, experiment, cost, bias, advanced-inference, adapter, and extension evidence without turning absent evidence into pass. |
| reproducible reports | Hardening | `0.7` adds deterministic, checksummed, independently verifiable bundles at the `identifiable` level. Recomputable/numerical claims remain out of scope until a verified reproducer exists. |
| Polars/pandas/Arrow interoperability | Released | Eager/lazy Polars, NumPy, optional pandas/Arrow, DuckDB Arrow streams, and adapter matrices run in CI. Broader cross-phase workflows remain a `0.8` integration check. |
| published benchmark suite | Released | Versioned Python artifact v4 and Criterion kernels cover public workflows; `0.9` must profile the integrated workflow and act only on measured bottlenecks. |
| cross-platform wheels | Released | Stable-ABI Linux x86_64/aarch64, macOS arm64, and Windows x86_64 wheels are target-smoke-tested, checksummed, and attested. |
| comprehensive methodology docs | Hardening | Every released analytical phase has methodology and subsystem contracts; `0.8`–`0.9` must close cross-links, complete integrated how-tos, and audit reference coverage. |
| real users on independent stacks | External | No independent users are currently available. Maintainer testing and CI do not satisfy this item; `1.0.0` remains blocked until real independent use is evidenced or the specification is explicitly changed. |

## Coherent pre-v1 milestones

The minor numbers are compatibility boundaries, not a calendar and not a promise to ship unrelated
features merely to consume a number.

### `0.7` — portable evidence

- deterministic `.lacuna` bundles;
- a published manifest schema and migration fixture;
- SHA-256 artifact-set and member verification;
- privacy redaction/fail-closed rules and hostile-archive defenses;
- Python and CLI creation/verification plus installed-wheel exercise.

### `0.8` — cross-phase standardized audit

The candidate scope is a versioned audit profile that accepts released evidence from signal,
validation, experiments, robustness, regimes, costs, bias, advanced inference, adapters, and
extensions. Design must preserve domain method semantics, distinguish required/optional/inapplicable
evidence, expose coverage by category, and avoid one misleading universal score. Complete
vendor/backtester-to-audit examples and bundle output belong in this milestone.

### `0.9` — migration and operational hardening

The candidate scope is persisted-artifact migration/read compatibility, integrated workload
benchmarks, installation diagnostics, bounded performance improvements, documentation reference
coverage, and defects found by real external use. Work that has no evidence-backed need does not
enter merely because `0.9` is the last pre-v1 minor.

## Stable-release decision

`1.0.0` requires every row to be released or otherwise satisfied with reviewable evidence. Internal
tests may close internal rows; they cannot close the independent-use row. The earlier maintainer
waiver that permitted the initial public release does not silently waive the technical
specification's v1 definition.

