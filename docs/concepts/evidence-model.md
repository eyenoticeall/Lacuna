# Results and evidence

Lacuna computes evidence first and renders it second. A chart, notebook display, or HTML report is never the authoritative result.

## Result shape

The implemented `AnalysisResult` foundation contains:

```text
schema_version
metadata
metrics
findings
tables
warnings
```

Domain-specific result types may add typed convenience properties, but they must preserve the same concepts and serialize predictably.

### Metrics

Metrics are scalar or small structured values intended for direct inspection. Names include units or make units unambiguous, for example `mean_ic`, `turnover_fraction`, or `break_even_cost_bps`.

### Tables

Tables are the source data for plots and detailed analysis. Renderers consume them without recomputing domain statistics. A user should be able to request the data behind any visualization.

### Findings

A finding separates outcome from materiality:

| Dimension | Values |
|---|---|
| State | `PASS`, `WARN`, `FAIL`, `UNKNOWN`, `NOT_APPLICABLE` |
| Severity | `info`, `low`, `medium`, `high`, `critical` |

`UNKNOWN` means relevant evidence was not supplied or cannot be established. `NOT_APPLICABLE` means the check genuinely does not apply. Neither is equivalent to `PASS`.

Each finding has a stable code, human title, explanatory message, category, and structured evidence. Codes are API: renaming one requires a migration note or method-version change.

## Provenance

Result metadata records at least:

- method and method version;
- effective parameters, including defaults that affect output;
- random seed when applicable;
- input fingerprint when available;
- creation timestamp;
- Lacuna version at the report or bundle boundary.

Future domain results should also support sample counts, effective sample size, data period, algorithm/backend selection, warnings, copy/materialization diagnostics, and relevant environment metadata.

Method versioning is independent of package versioning. Increment the method version when the same public call can produce meaningfully different values because a formula, edge-case policy, or algorithm changes.

## Immutability

Result objects behave as value objects:

- constructor inputs are defensively frozen or copied;
- methods do not mutate metrics or findings in place;
- derived presentations return new objects or external artifacts;
- caches key from serialized identity, not object identity;
- random state is not stored as a mutable generator inside the result.

## Serialization

Core serialization is versioned JSON. It must be valid interoperable JSON, not Python's extended representation:

- mapping keys are strings;
- NaN and infinity are rejected or represented through an explicit nullable/status field;
- timestamps are timezone-aware ISO 8601 strings;
- enums serialize to stable string values;
- no pickle or arbitrary class loading is required;
- unknown fields can be preserved or ignored according to the schema compatibility policy.

Markdown is a renderer over the structured result. HTML is optional and must escape user-provided labels and metadata.

The published v0.1 envelope is documented in
[Result schema compatibility](../reference/result-schema.md) and validated against a committed
representative fixture.

The v0.7 `.lacuna` boundary packages that unchanged result with deterministic report projections,
structured runtime context, optional named evidence, and a checksummed versioned manifest. Bundle
integrity and result meaning remain separate: `bundle_version` selects the archive contract,
`schema_version` selects the result envelope, and `method_version` selects analytical semantics.
See [Reproducibility bundle v1](../reference/reproducibility-bundle.md).

The v0.8 standardized audit consumes named `AnalysisResult` values without rerunning their methods.
Its profile schema is distinct from both the result envelope and bundle layout. Coverage findings
state whether accepted evidence is present; source findings are carried forward without threshold,
state, or severity reinterpretation. See
[Standardized cross-phase audit](../reference/standardized-audit.md).

## Findings lifecycle

An audit rule follows a deterministic lifecycle:

1. Determine applicability from available evidence.
2. If evidence is relevant but absent, emit `UNKNOWN` with the missing requirements.
3. Compute the rule from domain results, not raw presentation data.
4. Attach observed values, thresholds, and assumptions as structured evidence.
5. Assign state and severity independently.
6. Preserve rule and scoring-model versions in the audit result.

Thresholds are configuration, not hidden constants. A report explains why a state was assigned.

## Compatibility rules

Before v1.0, result schemas may evolve, but changes must update fixtures and the changelog. Once persisted audits are in use:

- additive optional fields are backward-compatible;
- field removal or semantic reuse requires a schema-version change;
- finding code changes require migration documentation;
- units may never change under the same field name;
- renderers should accept older supported schema versions without changing their recorded evidence.

## Required tests

Result types require:

- JSON round-trip fixtures;
- immutability tests including nested structures;
- rejection of non-finite JSON numbers and non-string keys;
- timezone validation;
- stable enum and finding-code serialization;
- deterministic ordering where snapshots depend on it;
- backward-compatibility fixtures once more than one schema version exists.
