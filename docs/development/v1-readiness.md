# v1 readiness ledger

This ledger maps the technical specification's `1.0.0` definition to released evidence and remaining
work. It prevents a long feature list from being mistaken for a stable product contract. Status is
evaluated in four states:

- **released** — the capability has a tagged public contract and release evidence;
- **hardening** — the capability exists, but cross-release or cross-subsystem evidence is incomplete;
- **missing** — the required internal contract is not implemented;
- **external** — completion depends on evidence the repository and CI cannot create.

## Definition ledger

| v1 definition item | Status after the `0.9` milestone | Evidence and remaining gate |
| --- | --- | --- |
| stable data-contract semantics | Released | Labels, adapters, point-in-time joins, dataset specs, and backtest schemas are released, documented, covered by frozen API series, and represented in the standardized profile and integrated workload. The `1.0` tag can make the long-term stability declaration without another internal implementation. |
| stable result schema | Released | `AnalysisResult` schema 1 has a strict non-executing reader, JSON Schema, golden fixture, additive API series, and tagged identity-migration evidence across every `0.1`–`0.8` producer line consumed by `0.9`. |
| mature signal diagnostics | Released | Forward labels, IC, quantiles, turnover, and multi-horizon decay shipped in `0.1`. |
| mature financial CV | Released | Walk-forward, purged K-fold, embargo, and CPCV/path evidence shipped through `0.5`. |
| robust bootstrap/permutation | Released | IID and dependent bootstrap plus explicit permutation nulls and deterministic streams shipped through `0.5`. |
| PSR/DSR | Released | Sharpe uncertainty, PSR, DSR, and minimum track-record evidence shipped in `0.5`. |
| multiple-testing support | Released | Bonferroni, Holm, BH, BY, PBO, Reality Check, and SPA are public with family-completeness contracts. |
| parameter stability | Released | Parameter surfaces, continuous perturbation, subperiods, and universe perturbation shipped in `0.2`. |
| regime analysis | Released | Fixed, trailing point-in-time, and explicitly retrospective regimes plus conditional evidence shipped in `0.2`. |
| cost stress | Released | Composable costs, stress scenarios, break-even, liquidity, and capacity evidence shipped in `0.3`. |
| point-in-time checks | Released | Availability-safe joins, revisions, future-data checks, survivorship, membership, drift, and dataset validation shipped in `0.4`. |
| standardized audit | Released | `0.8` profiles signal, strategy, and options scopes; recognizes every released method family; exposes categorical required/optional/not-applicable coverage; preserves source findings; and emits no universal cross-phase score. |
| reproducible reports | Released | Deterministic bundle v1 records input fingerprints, resolved configuration, Lacuna/method versions, seeds in report evidence, environment metadata, and checksummed report projections. Its explicit `identifiable` claim satisfies the specification without claiming inaccessible inputs or cross-machine numerical equality. |
| Polars/pandas/Arrow interoperability | Released | Eager/lazy Polars, NumPy, optional pandas/Arrow, DuckDB Arrow streams, and adapter matrices run in CI; vendor/backtester and options evidence enter the standardized profile in executable integration and wheel checks. |
| published benchmark suite | Released | Versioned Python artifact v5 and Criterion kernels cover public workflows; the deterministic integrated strategy-audit case has a measured profile and no unjustified production optimization. |
| cross-platform wheels | Released | Stable-ABI Linux x86_64/aarch64, macOS arm64, and Windows x86_64 wheels are target-smoke-tested, checksummed, and attested. |
| comprehensive methodology docs | Released | Every analytical phase has methodology and subsystem contracts; an exact machine-checked root/module export inventory routes every supported name to its semantic documentation. Independent-use defects remain external evidence, not missing documentation structure. |
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

- versioned built-in `signal`, `strategy`, and `options` profiles;
- a published profile JSON Schema, frozen strategy fixture, and additive public API fixture;
- unique method-family mapping across every released analytical and integration subsystem;
- categorical required/optional/not-applicable coverage without a universal score;
- source finding propagation without threshold, state, or severity reinterpretation;
- bounded strict result JSON ingestion and `lacuna audit --evidence NAME=PATH`;
- vendor/backtester example, options integration, deterministic bundle, and installed-wheel gates.

### `0.9` — migration and operational hardening

Completed internal scope:

- persisted-artifact identity migrations and strict current readers;
- tagged historical fixture identity and semantic round-trip regression tests;
- integrated benchmark artifact v5 plus profile-led performance review;
- stable-code installation diagnostics and strict automation exits;
- exact public export/reference/design-route coverage;
- clean-wheel, archive-content, extension-integration, and release gates for the new contracts.

No independent users were available, so `0.9` does not claim real-user validation or defects found
through it. That evidence is tracked only by the external row rather than fabricated or silently
waived.

## Stable-release decision

Every internal row now has released evidence. `1.0.0` remains blocked solely by the
independent-use row: repository tests cannot prove that real users can apply Lacuna on independent
research stacks. The earlier maintainer waiver that permitted the initial public release does not
silently waive the technical specification's v1 definition.
