# Experiments and reproducibility

**Status:** v0.2 implements canonical/versioned identities, append-only local SQLite attempts,
immutable corrections, complete selection lineage, registry snapshots, and basic multiplicity
correction. v0.7 adds deterministic identifiable-level reproducibility bundles with environment
summaries and independent integrity verification. Distributed registries, remote artifact stores,
and verified recomputation remain later work.

An experiment registry is the memory of the research process. It records all evaluated variants, not only the winner, so selection bias and multiple testing can be measured instead of guessed.

## Ownership

The implemented `lacuna.experiment` module owns:

- experiment, family, and trial identity;
- canonical parameter encoding;
- trial lifecycle and append-only records;
- dataset/code/environment fingerprints;
- selection records;
- cache keys and artifact manifests;
- reproducibility bundles.

Statistical modules consume the trial history for multiple-testing corrections. They do not own storage. Reporters render registry evidence but do not rewrite it.

## Identity hierarchy

- **experiment family**: the declared research question and comparable search space;
- **experiment**: a particular protocol, dataset scope, and methodology configuration;
- **trial**: one fully specified parameterization and execution;
- **attempt**: an execution attempt for a trial, including failures or retries;
- **selection**: a recorded decision to advance one or more trials using a declared criterion.

Human names are labels, not identifiers. IDs should be stable, opaque, and collision-resistant.

## Canonical trial record

A trial record should include:

- family, experiment, trial, and attempt IDs;
- creation/start/end timestamps in UTC;
- canonical parameters and methodology configuration;
- input dataset fingerprints and semantic column mappings;
- code identity and dirty-worktree state;
- package, schema, and method versions;
- RNG algorithm, seed/root entropy, and substream identity;
- execution backend, thread budget, and environment summary;
- status, structured error category, and artifact references;
- compact primary metrics and the complete result reference;
- whether the trial was selected, when, why, and by which criterion.

Failed and cancelled attempts are evidence. Preserve them rather than overwriting the record with a successful retry.

## Canonicalization and fingerprints

Fingerprint inputs must be canonical before hashing:

- mappings have sorted string keys;
- datetimes are UTC ISO 8601 with declared precision;
- enums use stable string values;
- floating values have an explicit binary or decimal encoding;
- sets are rejected or converted by a declared ordering;
- callable identity is represented by registered name and version, not memory address;
- NaN and infinity are prohibited in canonical JSON.

c14n-v1 fingerprints accept numeric NumPy arrays and Polars frames as logical equivalents of their
existing nested-list and row-record representations. They encode them in bounded one-MiB batches,
so inference callers do not first construct whole `.tolist()` or `.to_dicts()` trees. Key sorting,
row order, scalar formatting, signed-zero normalization, date/time conversion, sensitive-key
rejection, and SHA-256 prefixes/digests remain byte-identical. Physical array contiguity, Polars
chunk layout, and dataframe column order do not change a logical fingerprint; row order does.
`canonical_json()` retains its public string return and existing accepted-input contract.

A fingerprint descriptor includes the hash algorithm and canonicalization version. Changing canonicalization rules changes that version. A BLAKE3 content fingerprint is a reasonable target, but the public contract should not imply that two equal fingerprints prove the semantic equivalence of unmodeled external state.

### Dataset fingerprints

The dataset fingerprint strategy must be explicit:

- content hash for immutable local artifacts;
- provider snapshot/version plus query fingerprint for managed data;
- partition-manifest hash for large datasets;
- user-supplied identity only when clearly marked unverified.

Schema, row count, time range, entity count, and source URI class are recorded alongside the digest. Credentials and signed URLs are excluded.

### Code identity

Prefer a source distribution/version plus VCS commit. Record whether relevant files were dirty and, if practical, a hash of the diff without storing secrets. Installed package versions alone are insufficient for editable installs.

## Append-only registry behavior

Completed attempts are immutable. Corrections create a superseding record that references the original and states why. The storage layer should use atomic writes or transactions and protect against two workers claiming the same attempt.

Registry queries may provide a mutable view, but the underlying records remain auditable. Schema migration preserves original data and records the migration tool/version.

## Selection lineage and multiple testing

Every selection records:

- candidate family and eligible trial IDs;
- metric and direction;
- tie-breaking policy;
- constraints and exclusion reasons;
- whether the decision used test/holdout evidence;
- decision timestamp and actor label.

The full candidate set feeds methods such as Bonferroni, Holm, Benjamini-Hochberg, deflated Sharpe ratio, and later probability of backtest overfitting. Excluding failed, unselected, or inconvenient trials must be an explicit policy, not an accidental query filter.

## Caching

A cache key includes every input that can change the result:

- method name and version;
- normalized parameters;
- data and code fingerprints;
- relevant semantic configuration;
- backend and numerical mode when they can affect results;
- RNG identity for randomized methods.

Do not cache mutable Python objects by identity or reuse cached artifacts when any component is unknown. Cache artifacts are content-addressed where practical, validated on read, and safe to delete without losing registry history.

## Reproducibility bundle

The implemented v0.7 boundary is `AuditReport.bundle(path, ...)`, the equivalent
`lacuna.create_bundle(report, path, ...)`, and `lacuna.verify_bundle(path)`. Bundle v1 includes the
canonical audit, Markdown/HTML projections, resolved configuration, an environment summary, and
optional `AnalysisResult` evidence/provenance/invocation metadata. It publishes a JSON Schema and
strictly verifies canonical paths, file types, JSON, sizes, artifact-set/member SHA-256, and archive
membership without extraction or execution.

See the [bundle v1 reference](../reference/reproducibility-bundle.md) for the exact layout, API,
limits, privacy rules, determinism scope, and compatibility behavior.

A bundle manifest should identify:

- the canonical report and result artifacts;
- normalized configuration;
- experiment and selection records;
- environment/lockfile summary;
- code and dataset fingerprint descriptors;
- method and schema versions;
- deterministic command or API invocation where representable;
- artifact digests, sizes, and media types.

The default bundle does not copy proprietary input data, credentials, machine-specific absolute paths, or unredacted environment variables. It may contain a retrieval recipe or data manifest if redistribution is not permitted.

Reproduction has levels:

1. **identifiable** — dependencies and inputs have stable identities;
2. **recomputable** — the environment and inputs are accessible;
3. **numerically reproducible** — results meet declared tolerances;
4. **bitwise reproducible** — bytes match, where supported.

Reports must claim only the level verified.

Bundle v1 claims only level 1. A checksummed archive establishes identity and corruption detection;
it does not make inaccessible data accessible, run a computation, compare numerical tolerances, or
authenticate the author. Higher-level claims remain future work.

## Concurrency and remote execution

Workers should obtain an attempt lease or use a uniqueness constraint. Retried work receives a new attempt ID but retains the same trial ID when parameters and semantic inputs are unchanged.

Clock timestamps are operational metadata, not the only event order. Use monotone attempt sequence numbers or transactional ordering. Remote workers return artifacts through a validated manifest; the coordinator commits final registry state.

## Security and privacy

- redact secrets and credential-shaped environment variables;
- normalize or omit user/machine paths;
- validate artifact paths against the bundle root;
- never unpickle untrusted registry artifacts;
- treat imported plugin metadata and annotations as untrusted text;
- record external URIs without embedding short-lived tokens.

## Required tests

- reordered parameter mappings produce the same fingerprint;
- materially different parameters, method versions, or data manifests do not;
- NaN, infinity, sets, and opaque callables fail canonicalization clearly;
- failed attempts remain visible after a successful retry;
- concurrent writers cannot finalize the same attempt twice;
- selection records preserve the full eligible candidate set;
- cache misses occur when any semantic dependency changes;
- bundle manifests reject path traversal and digest mismatches;
- secrets and signed-query parameters are redacted;
- bundle reproduction meets its declared tolerance level.
