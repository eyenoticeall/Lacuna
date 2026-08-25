# Experiment lineage and multiple testing

Research selection is part of the evidence. A reported winner is not a one-trial result when many
variants, retries, failures, or judgment calls preceded it. Lacuna v0.2 provides a local append-only
registry and four basic p-value corrections so the declared trial family can be inspected and
adjusted rather than reconstructed from memory.

## Canonical identity

`lacuna.experiment.canonical_json()` normalizes supported identity inputs before hashing:

- mapping keys are sorted strings;
- aware datetimes are converted to UTC ISO 8601;
- dates and enums use stable textual values;
- positive and negative floating-point zero are identical;
- lists and tuples preserve order;
- finite integers and floating-point values remain numeric.

It rejects NaN, infinity, naive datetimes, unordered sets, opaque callables, non-string mapping
keys, unsupported objects, and credential-looking keys. A callable belongs in identity as a
registered `method` plus `method_version`, not as a process-local function address.

`fingerprint(value, namespace=...)` hashes the canonical payload with SHA-256 and includes both the
namespace and canonicalization version. Namespaces prevent the same bytes from silently serving as
a dataset ID, trial ID, and result ID. A fingerprint proves equality of the modeled payload; it
cannot prove semantic equality of state that was omitted.

## Trial and attempt identity

An `ExperimentRegistry` contains experiments within a declared family:

```python
import lacuna as lc

registry = lc.ExperimentRegistry(
    "momentum-search",
    family="cross-sectional-momentum",
    path="experiments.sqlite3",
)
```

A trial ID is deterministic over:

- registry family and experiment name;
- canonical parameters;
- method name and method version;
- data fingerprint;
- code fingerprint.

An attempt ID is unique per execution. This separation makes a failed run, retry, and corrected run
three immutable attempts for one trial rather than three apparently independent trials.

```python
failed = registry.record(
    parameters={"lookback": 40},
    status="failed",
    error_category="NumericalError",
    method="strategy.evaluate",
    data_fingerprint="dataset:2026-08-26",
    code_fingerprint="git:abc123",
)

retry = registry.record(
    parameters={"lookback": 40},
    metric=0.014,
    metric_name="p_value",
    method="strategy.evaluate",
    data_fingerprint="dataset:2026-08-26",
    code_fingerprint="git:abc123",
)
```

Failures require a structured error category and cannot store a metric. Completed attempts cannot
store an error category. Exception messages and tracebacks are intentionally not registry fields;
they frequently contain paths, queries, or secrets. Callers can store a safe external artifact
reference in metadata when required.

## Corrections are append-only

Existing rows are never edited. A correction must reference an attempt for the same deterministic
trial and state why it supersedes the earlier evidence:

```python
corrected = registry.record(
    parameters={"lookback": 40},
    metric=0.018,
    metric_name="p_value",
    method="strategy.evaluate",
    data_fingerprint="dataset:2026-08-26",
    code_fingerprint="git:abc123",
    supersedes_attempt_id=retry.attempt_id,
    supersedes_reason="Corrected upstream partition manifest",
)
```

The SQLite backend uses transactions, foreign keys, uniqueness constraints, a busy timeout, and WAL
mode for file registries. Separate connections cannot claim the same explicit attempt ID. This is a
local concurrency guarantee, not a distributed scheduler or exactly-once execution protocol.

## Selection lineage

A selection records the complete eligible set, the selected subset, direction, metric, tie policy,
holdout use, optional actor, and explicit exclusions:

```python
attempts = registry.attempts()
selection = registry.record_selection(
    eligible_trial_ids=sorted({attempt.trial_id for attempt in attempts}),
    selected_trial_ids=[corrected.trial_id],
    metric="p_value",
    direction="minimize",
    tie_breaking="lower_turnover_then_trial_id",
    used_holdout=False,
)
```

Selected IDs must belong to the eligible set, every eligible trial must already exist, and selected
trials cannot also have exclusion reasons. Failed or inconvenient trials do not disappear merely
because they were not selected.

`registry.to_result()` returns an immutable `AnalysisResult` snapshot with attempt and selection
tables, counts, versioned storage metadata, and a snapshot fingerprint. A local registry cannot
prove that the researcher recorded every trial run elsewhere; Lacuna reports that limitation rather
than converting absence into a pass.

## Multiplicity corrections

`lacuna.validation.multiple_testing()` accepts a registry, a one-dimensional numeric sequence, a
NumPy vector, or a table with stable trial and p-value columns. P-values must be finite and in
`[0, 1]`; trial identities must be unique. Registry input requires every current trial attempt to be
completed with the requested metric name.

For ordered p-values \(p_{(1)} \le \dots \le p_{(m)}\):

| Method | Adjustment | Intended control |
| --- | --- | --- |
| Bonferroni | \(\min(1, m p_i)\) | family-wise error rate under arbitrary dependence |
| Holm | cumulative maximum of \((m-i+1)p_{(i)}\) | step-down family-wise error rate |
| Benjamini-Hochberg | reverse cumulative minimum of \(m p_{(i)}/i\) | false discovery rate under independence or positive dependence |
| Benjamini-Yekutieli | BH multiplied by \(\sum_{i=1}^m 1/i\) | conservative false discovery rate under arbitrary dependence |

```python
adjusted = lc.validation.multiple_testing(
    registry,
    p_value="p_value",
    method="holm",
    alpha=0.05,
)
```

The `adjusted_p_values` table preserves input trial order and adds rank, adjusted p-value, and
rejection state. Ties use stable input order for rank assignment but receive adjustment values from
the same monotone procedure. Benjamini-Hochberg emits its dependence assumption as a warning.

An optional user-supplied effective trial count is supported only for Bonferroni. Lacuna does not
estimate it in v0.2 and labels it as user-supplied. Do not choose an effective count after seeing the
desired significance result.

## What adjustment does not repair

Multiplicity correction assumes valid underlying p-values and a defensible family definition. It
does not fix look-ahead, invalid dependence assumptions in the original test, outcome switching,
unrecorded trials, biased universe construction, or reuse of a final holdout. Those remain separate
findings and provenance requirements.
