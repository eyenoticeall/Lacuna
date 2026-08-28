# Standardized cross-phase audit

Lacuna's standardized audit composes immutable evidence produced by the released analytical,
adapter, plugin, and extension boundaries. It does not rerun those methods, reinterpret their
thresholds, or reduce unlike research questions to one quality number.

The public entry point is `lacuna.standard_audit(...)`. The original `lacuna.audit(...)` and
`SignalStudy.audit(...)` retain the frozen signal-audit contract from `0.1.x`; the standardized
profile is additive in `0.8.x`.

## Why a profile exists

A strategy audit and a signal-only study should not pretend to require identical evidence. A
versioned profile answers four separate questions:

1. Which method families count toward each research capability?
2. Is that capability required, optional, or not applicable for the selected scope?
3. Was recognized evidence supplied?
4. What did the source method itself conclude?

Questions 3 and 4 are intentionally separate. `PASS` on an `EVIDENCE_*` finding means only that a
recognized result was supplied for that capability. Source findings are propagated separately with
their original state, severity, category, message, and structured evidence.

## Built-in scopes

`standard_profile(scope)` returns one immutable v1 profile:

| Capability | Accepted method identities | Signal | Strategy | Options |
| --- | --- | --- | --- | --- |
| signal diagnostics | `labels.*`, `signal.*` | Required | Optional | Optional |
| temporal validation | `cv.*` | Required | Required | Required |
| resampling inference | `validation.bootstrap.*`, `validation.permutation.*` | Required | Required | Required |
| advanced inference | Sharpe, PBO, joint bootstrap, Reality Check, SPA | Optional | Required | Required |
| experiment lineage | `experiment.*` | Required | Required | Required |
| multiple testing | `validation.multiple_testing.*` | Required | Required | Required |
| parameter robustness | parameter surfaces, continuous perturbation | Required | Required | Required |
| temporal robustness | subperiod analysis | Required | Required | Required |
| universe robustness | universe perturbation | Required | Required | Optional |
| regime robustness | `regime.*` | Required | Required | Optional |
| execution realism | `costs.*` | Not applicable | Required | Required |
| point-in-time data | as-of join, future/revision checks, dataset validation | Required | Required | Required |
| survivorship | survivorship diagnostics, historical membership, universe drift | Required | Required | Optional |
| adapter provenance | `adapters.*` | Optional | Optional | Optional |
| plugin provenance | `plugins.*` | Optional | Optional | Optional |
| options evidence | `options.*` | Not applicable | Not applicable | Required |

The matrix is a coverage contract, not a claim that one result from a broad family exhausts every
possible check. A supplied `costs.stress` result satisfies the execution-realism capability row; its
own findings still determine what that cost experiment established. Detailed methodology remains in
the relevant subsystem result.

`Not applicable` is scope-specific. Supplying matching evidence to such a row emits `WARN` instead
of silently discarding it, because the selected scope may be wrong. An absent optional row is
`NOT_APPLICABLE` to profile completeness. An absent required row is `UNKNOWN`, never `PASS`.

## Python workflow

Evidence names are caller-controlled stable identifiers within one audit. Result method identity,
not the evidence name, determines the capability:

```python
import lacuna as lc

evidence = {
    "purged_split": split.evidence,
    "experiment_registry": registry.to_result(),
    "parameter_surface": surface,
    "cost_stress": stressed_costs,
    "future_data": future_data_check,
    "vendor_prices": adapted_vendor.evidence,
    "backtest_returns": adapted_returns.evidence,
}

report = lc.standard_audit(
    results=evidence,
    scope="strategy",
)

print(report.summary())
print(report.table("category_coverage"))
report.to_json("strategy-audit.json")
report.bundle(
    "strategy-audit.lacuna",
    evidence=evidence,
    configuration={"audit_profile": "standard.strategy"},
)
```

Lower-level callers can construct `AuditContext` and call `run_standard_audit`. A custom
`AuditProfile` is supported for an explicitly versioned organizational contract. Built-in and
custom patterns are exact method names or prefix patterns with one trailing `*`. If a source method
matches multiple capabilities, evaluation fails closed rather than selecting by order.

The declared `policies["study_type"]`, when supplied, must equal the selected scope. This prevents a
context assembled as signal-only from being relabeled as a strategy audit by mistake.

## Result contract

The output remains an `AnalysisResult` schema-v1 object with:

- `metadata.method = "audit.standard"`;
- `metadata.method_version = 1`;
- profile, scope, coverage-rule, source-method, and policy identity in parameters;
- no `robustness_score` field and `score_model = null`;
- finite coverage and count metrics;
- coverage findings plus unmodified source finding semantics;
- four compact evidence tables.

### Metrics

| Metric | Meaning |
| --- | --- |
| `required_evidence_coverage` | required capabilities with at least one recognized result divided by required capabilities |
| `optional_evidence_coverage` | supplied optional capabilities divided by optional capabilities |
| `required_evidence_complete` | whether every required capability is represented |
| `supplied_result_count` | all named inputs, recognized or not |
| `recognized_result_count` | inputs matched to exactly one capability |
| `unrecognized_result_count` | inputs retained in inventory but excluded from coverage |
| `domain_finding_count` | source findings propagated without reinterpretation |
| state counts | counts over coverage, source, and unrecognized-evidence findings |

`evidence_coverage` aliases required coverage so generic report consumers can display the result.
It is not a probability, statistical confidence, expected return, profitability estimate, or
strategy-quality score.

### Tables

| Table | Purpose |
| --- | --- |
| `category_coverage` | required/optional/not-applicable totals and presence by stable audit category |
| `evidence_requirements` | full capability matrix, accepted methods, disposition, and matching source names |
| `evidence_inventory` | every supplied name, method/schema version, capability, finding/warning counts, and seed/fingerprint presence |
| `domain_findings` | original source finding identity, state, severity, category, message, and evidence |

Renderers consume these stored values. Markdown and HTML display a categorical assessment and do
not synthesize a score.

## Finding identity and propagation

Coverage finding codes are stable `EVIDENCE_<CAPABILITY>` identifiers. Propagated findings receive a
deterministic `DOMAIN_<CAPABILITY>_<DIGEST>` envelope code so duplicate source codes cannot collide.
The original code and all source semantics remain in structured evidence:

```text
profile_capability
source_name
source_method
source_method_version
source_finding_code
source_category
source_evidence
propagated_without_reinterpretation = true
```

Changing a domain threshold still belongs to that domain method/finding version. Changing profile
applicability, method-family membership, or coverage behavior requires a profile or coverage-rule
version change.

## CLI workflow

Persisted inputs use the strict current result-envelope reader:

```bash
lacuna audit \
  --scope strategy \
  --evidence split=artifacts/purged-split.json \
  --evidence trials=artifacts/experiment-snapshot.json \
  --evidence costs=artifacts/cost-stress.json \
  --evidence bias=artifacts/future-data.json \
  --format html \
  --out strategy-audit.html \
  --bundle strategy-audit.lacuna
```

Each `NAME` matches `[a-z][a-z0-9_-]{0,63}` so it is valid both in the CLI and as a conservative
bundle member name. Names must be unique. Each file
is limited to 16 MiB and must be UTF-8 `AnalysisResult` schema-v1 JSON. The reader rejects:

- unsupported schema versions;
- missing or additional envelope/finding fields;
- duplicate JSON object keys at any depth;
- `NaN`, positive infinity, and negative infinity;
- invalid states, severity values, timestamps, seeds, and method versions;
- non-object top-level content.

Requested report content goes to stdout; file and bundle write diagnostics go to stderr. Existing
artifacts require `--overwrite`. Exit `1` means execution/input failure. Exit `3` means
`--fail-on fail` or `--fail-on warn` matched a finding. Missing required evidence is `UNKNOWN`; the
current fail policy does not conflate it with a confirmed failure.

## Vendor, backtester, plugin, and extension evidence

Adapters contribute provenance, not analytical conclusions. A `VendorSchema` result can prove that
availability/revision/identity semantics were declared and retained; it cannot independently prove
the vendor archive was historically complete. A `BacktestSchema` result preserves gross/net,
timing, compounding, costs, borrow, calendar, and delisting assumptions; it does not perform a
backtest or cost analysis.

The executable `examples/standard_audit.py` shows both boundaries entering a strategy profile.
Their adapter capability is optional, while absent required statistical, robustness, execution,
and bias evidence remains visible as `UNKNOWN`.

Plugin activation evidence is accepted only after the caller explicitly activated trusted
in-process code. Reading a report, profile, JSON result, or bundle never discovers or activates a
plugin. `lacuna-options` results enter the required `options_evidence` row only under the options
scope; the separately versioned extension remains optional to core.

## Profile schema and compatibility

`AuditProfile.to_dict()` emits the portable definition selected by
`schema_version = "1"`. The JSON Schema is published at
`schemas/standard-audit-profile-v1.schema.json` and packaged as
`lacuna.schemas.standard_audit_profile_v1_text()`. A frozen `standard.strategy` fixture detects
unreviewed changes. `AuditProfile.from_dict(...)` and `from_json(...)` read that exact definition
without discovering or activating plugins; duplicate keys, non-finite values, unsupported fields,
and unknown versions fail closed.

Three versions remain independent:

- result `schema_version` selects the generic evidence envelope;
- audit `profile_version` selects capability/applicability meaning;
- each source `method_version` selects its domain semantics.

Bundle versioning remains independent as well. A bundle stores the completed audit and optional
source evidence as data. Its SHA-256 verifier proves archive integrity, not the truth of a vendor
declaration, independent recomputation, authorship, or strategy quality.

## Review checklist

Before changing a profile:

1. Confirm the capability belongs to audit orchestration rather than a domain method.
2. Document why each scope marks it required, optional, or not applicable.
3. Ensure every accepted method maps to exactly one capability.
4. Preserve source states, severities, thresholds, and structured evidence.
5. Increment the profile or coverage-rule version when meaning changes.
6. Update the published schema, frozen profile/API fixtures, CLI/help, docs, wheel smoke, and release
   archive checks.
7. Test missing, optional, inapplicable-but-supplied, unrecognized, overlapping, duplicate-name,
   hostile-JSON, extension, rendering, and bundle paths.
