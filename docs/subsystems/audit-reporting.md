# Audit engine and reporting

**Status:** the v0.1 signal rule protocol, explicit applicability states, versioned scoring,
`SignalStudy` orchestration, and deterministic JSON/Markdown/basic HTML renderers are implemented.
v0.7 adds checksummed reproducibility bundles. v0.8 adds separately versioned signal, strategy,
and options cross-phase profiles with categorical coverage and no universal score. v0.10 adds an
immutable named-evidence mapping and an optional evidence-native Plotly renderer. Third-party rule
loading remains later work. v0.11 extends stored-row views to validated decay fits, diagnostic
portfolio cohorts, and event response bands.

The audit engine turns analytical evidence into reviewable findings. Reporting renders that evidence. Keeping the two separate prevents presentation choices from changing audit conclusions.

## Architecture

```text
analysis results + provenance + optional context
                       │
                       ▼
                  audit rules
                       │
                       ▼
          findings + score + evidence tables
                       │
                       ▼
        JSON / Markdown / HTML / terminal renderers
```

`lacuna.audit` owns rule execution, applicability, findings, and scoring. `lacuna.report` owns serialization and presentation. Renderers consume an immutable audit result; they do not execute analyses or reinterpret severity.

## Public v0.1 workflow

The high-level study delegates to the functional label, signal, validation, and audit APIs:

```python
import lacuna as lc

study = lc.SignalStudy(
    signal=signal,
    prices=prices,
    horizons=("1D", "5D", "20D"),
    price_adjustment="total_return_adjusted",
    quantiles=5,
)
report = study.audit(
    bootstrap_resamples=10_000,
    seed=42,
    policies={
        "survivorship_safe": True,
        "trial_history_available": True,
    },
)

print(report.summary())
report.to_markdown("lacuna-audit.md")
report.to_html("lacuna-audit.html")
report.to_html("lacuna-signal.html", renderer="plotly", view="signal")
report.to_json("lacuna-audit.json")
report.bundle("study.lacuna")
```

Lower-level callers can assemble evidence explicitly with `AuditContext` and `run_audit`, or
call `lacuna.audit(results=..., policies=...)`. This is useful when the analysis was computed by
separate jobs. Result names are part of the v0.1 audit contract: `labels`, `ic`, `quantiles`,
`turnover`, `decay`, `bootstrap`, and `split`.

`SignalStudy.audit(additional_evidence=...)` retains those results in `report.evidence`. The mapping
is immutable and sorted by source name. `report.table(name)` checks the audit result first and then
named evidence; if multiple sources contain the same table, callers must use
`report.table(name, source="ic")`. Direct `AuditReport(result)` construction still has no retained
analytical evidence, preserving its prior bundle behavior.

## Interactive evidence views

HTML remains `renderer="core"` by default. `renderer="plotly"` is use-site optional through
`lacuna[report]` and accepts `auto`, `audit`, `signal`, `portfolio`, or `event` views. A missing
Plotly/Jinja2 installation raises an actionable `ReportError`; importing `lacuna` never imports
either dependency.

Panels render only rows already present in named `AnalysisResult` tables. Initial views cover IC,
bucket/quantile returns and spread, turnover/autocorrelation by lag, decay, attrition, and audit
coverage/findings. Every panel exposes source, table, fields, renderer version, and plotting
configuration. IDs and ordering are fixed, source-derived text is escaped, JSON remains finite,
Plotly JavaScript is embedded locally, and no table is sampled. A table over the bounded renderer
limit is omitted with a visible notice.

`AuditReport.to_json()` remains canonical audit-result schema-v1 JSON and therefore does not merge
named evidence into the envelope. Study bundles include retained evidence through the existing
bundle-v1 evidence layout. Renderers never revise findings, thresholds, or metrics.

## Standardized cross-phase workflow

`standard_audit` composes already-computed evidence from every released subsystem:

```python
report = lacuna.standard_audit(
    results={
        "split": split.evidence,
        "trials": registry.snapshot(),
        "surface": parameter_surface,
        "costs": cost_stress,
        "future_data": future_data,
        "vendor": adapted_vendor.evidence,
    },
    scope="strategy",
)
```

The built-in profile classifies method identities into explicit capabilities and declares each
required, optional, or not applicable for `signal`, `strategy`, or `options`. Missing required
capabilities emit `UNKNOWN`; absent optional or genuinely inapplicable capabilities emit
`NOT_APPLICABLE`; evidence supplied to a not-applicable row emits `WARN` so a scope mismatch cannot
hide.

Coverage findings do not reinterpret domain results. Source findings are propagated with their
original state, severity, category, message, evidence, method, and finding code. The standardized
report exposes required and optional coverage plus category, requirement, inventory, and domain-
finding tables. It deliberately omits `robustness_score` because weights across signal efficacy,
temporal validity, execution realism, and source provenance would imply unsupported comparability.

See the [standardized-audit reference](../reference/standardized-audit.md) for the complete method
matrix, CLI, JSON reader, bundle, compatibility, and review contracts.

## Audit context

Rules receive an `AuditContext`, not an unrestricted study object. The context may contain:

- named `AnalysisResult` objects;
- dataset and experiment provenance;
- declared methodology and policy settings;
- optional benchmark or baseline evidence;
- user-provided annotations that are clearly marked as such.

Context construction validates identifiers and versions once. Rules must treat it as read-only.

## Rule protocol

Conceptually, a rule exposes:

```python
class AuditRule(Protocol):
    rule_id: str
    rule_version: int

    def applicable(self, context: AuditContext) -> Applicability: ...
    def evaluate(self, context: AuditContext) -> Finding: ...
```

Applicability is structured and includes a state plus a reason. A rule that lacks required evidence returns `UNKNOWN` or `NOT_APPLICABLE`; it must not invent defaults or silently disappear.

Rules should be:

- deterministic and side-effect free;
- independently executable;
- explicit about required evidence;
- narrow enough to yield one actionable conclusion;
- versioned whenever thresholds or logic change.

Unexpected rule exceptions fail the audit run by default. A best-effort reporting mode may convert them to internal-error findings, but it must make the incomplete run unmistakable.

## Finding model

Every finding contains:

- stable `finding_id` and `rule_id`;
- rule and method versions;
- category and short title;
- state: `PASS`, `WARN`, `FAIL`, `UNKNOWN`, or `NOT_APPLICABLE`;
- severity independent of state;
- concise explanation and recommended action;
- structured evidence references and compact metrics;
- affected scope such as period, asset group, or experiment family;
- deterministic ordering key.

Severity expresses potential consequence; state expresses observed evidence. A high-severity rule can pass. An unknown state can be important without being mislabeled as a confirmed failure.

Findings must not contain arbitrary exception strings, secrets, raw proprietary datasets, or user-controlled HTML.

In v0.1, `Finding.code` is the stable rule identifier because every built-in rule produces one
aggregate finding. Separate finding-instance IDs and scoped recommendations are reserved for rules
that can produce multiple findings later.

## Categories

Initial categories should remain stable:

- `data_integrity`;
- `temporal_integrity`;
- `statistical_validity`;
- `robustness`;
- `costs_capacity`;
- `experiment_integrity`;
- `reproducibility`;
- `operational`.

New categories require an architecture decision because they affect filters, scores, report navigation, and compatibility.

## Scoring

A score is a review aid, not a proof of strategy quality. Its configuration must include:

- `score_version`;
- rule weights and severity mapping;
- treatment of `UNKNOWN` and `NOT_APPLICABLE`;
- aggregation and rounding policy;
- minimum evidence requirements.

Score computation should use unrounded internal values and round only for display. `NOT_APPLICABLE` is excluded from the denominator. `UNKNOWN` receives an explicit configurable treatment and is always reported separately so a high score cannot hide missing evidence.

The default report should show state counts and missing-evidence coverage next to the score.

### v0.1 score policy

The default score is version 1. Rule weights total 100 after the signal-only transaction-cost rule
is excluded. State credit is `PASS = 1`, `WARN = 0.5`, and `FAIL = UNKNOWN = 0`.
`NOT_APPLICABLE` is removed from both numerator and denominator. The computation is:

```text
score = 100 × Σ(rule_weight × state_credit) / Σ(applicable_rule_weight)
evidence_coverage = assessed_weight / applicable_weight
```

`UNKNOWN` remains in the score denominator but not the coverage numerator. A missing high-weight
check therefore lowers both the score and visible evidence coverage; it cannot disappear as an
implicit pass.

The implemented rule set is:

| Rule | Weight | Evidence or policy | Main v0.1 decision |
| --- | ---: | --- | --- |
| `IC_DEFINED` | 12 | `ic` | aggregate IC exists |
| `IC_PERIOD_SUPPORT` | 12 | `ic` | pass at 60 periods, warn at 20 |
| `QUANTILE_MONOTONICITY` | 10 | `quantiles` | pass at 0.7, warn at 0.4 |
| `BOOTSTRAP_INTERVAL` | 12 | `bootstrap` | pass if interval is positive |
| `HORIZON_DECAY_COVERAGE` | 10 | `decay` | pass at three horizons, warn at two |
| `LABEL_INTERVALS_PRESENT` | 10 | `labels` | explicit forward-label timing evidence |
| `PURGED_VALIDATION_SUPPLIED` | 10 | `split` | evidence must come from `cv.purged_kfold` |
| `PRICE_ADJUSTMENT_DECLARED` | 8 | `labels` | adjustment semantics are not unknown |
| `DELISTING_HANDLING_DECLARED` | 8 | `labels` | a delisting-return field was supplied |
| `TURNOVER_MEASURED` | 4 | `turnover` | rank turnover is defined |
| `SURVIVORSHIP_HANDLING_DECLARED` | 2 | policy | historical-universe safety is declared |
| `TRIAL_HISTORY_AVAILABLE` | 2 | policy | full research trial history is declared |
| `TRANSACTION_COST_EVIDENCE` | 4 | policy | not applicable to a signal-only study |

This scoring policy remains specific to the frozen v0.1 signal audit. The v0.8 standardized profile
does not reuse, rescale, or average these weights.

Threshold or weight changes require a rule or score version change. A score is an audit summary,
not a probability of future profitability.

## Deterministic output

Repeated rendering of the same audit result must produce semantically identical output. Define ordering for:

- findings: category, severity rank, rule ID, scope;
- tables: declared sort keys;
- mappings: canonical key order in JSON;
- floating-point display: fixed, documented formatting;
- timestamps: UTC ISO 8601;
- absent values: JSON `null`, never NaN or infinity.

Generated-at timestamps belong in bundle metadata and may be excluded from reproducibility comparisons.

## JSON

JSON is the canonical machine-readable report. It should have a published schema containing:

- report, package, schema, method, and score versions;
- run and experiment identifiers;
- summary and coverage;
- findings;
- evidence-table descriptors or inline compact tables;
- provenance and environment summary;
- artifact manifest.

Large tables should be referenced as typed artifacts rather than embedded without bound. Consumers must reject unsupported major schema versions.

The v0.1 JSON is `AnalysisResult` schema version `1`, published at
`schemas/audit-result-v1.schema.json`. It contains canonical finite values, audit
method and score versions, rule versions, summary metrics, findings, compact score tables, warnings,
and result-method provenance. Artifact manifests and large external evidence tables are later bundle
features.

The schema is exercised against `tests/fixtures/audit-result-v1.json`; the same representative
result also has a byte-stable Markdown fixture. Consumers must select a validator by
`schema_version` and reject unsupported major versions rather than guessing compatibility.

## Markdown and terminal output

Markdown should optimize for code review and issue attachment:

1. identity and reproducibility summary;
2. decision summary and evidence coverage;
3. failures and warnings;
4. unknown or unavailable checks;
5. key evidence tables;
6. methodology and provenance appendix.

Source-derived HTML metacharacters, table delimiters, backslashes, newlines, and control characters
are escaped or normalized before Markdown output. A downstream renderer must never receive a
source-provided `<script>` or event-handler element as live embedded HTML.

Terminal output is a compact view of the same data and uses text labels in addition to color. `--no-color` must be supported. Exit-code behavior belongs to the CLI contract and should distinguish execution failure from an audit containing failed findings.

`AuditReport` provides in-memory `to_json()`, `to_markdown()`, and `to_html()` calls. Passing a path
persists the corresponding format with exclusive creation by default; pass `overwrite=True`
explicitly to replace a file. `write(path, format=...)` is the format-selecting equivalent.

`AuditReport.bundle(path, ...)` creates the versioned portable evidence boundary. It stores those
same projections, never recomputes them, and may add named `AnalysisResult` evidence. The archive's
internal SHA-256 verification is not an authenticity signature. See the
[bundle v1 reference](../reference/reproducibility-bundle.md).

## HTML and plots

HTML rendering must escape all source-derived text and avoid executable inline content by default. If templates allow styling, keep assets local or content-addressed so offline reports remain complete.

Plots are projections of stored evidence tables. A renderer must not recompute statistical results. Every plot records its source table, selected columns, filters, and rendering configuration.

## Extensibility

Third-party rule loading is explicit. Discovering an entry point does not authorize its execution. A caller enables a plugin by identifier, and the report records its distribution name, version, entry point, and rule versions.

Plugin rules receive the same constrained context and return schema-validated findings. Python plugins are trusted code and must be described as such; Lacuna does not imply sandboxing.

## Required tests

- missing required evidence yields `UNKNOWN` with a useful reason;
- inapplicable methodology yields `NOT_APPLICABLE`;
- rule order does not change normalized output;
- score fixtures cover every state and severity;
- changing a threshold requires/challenges a rule version change;
- JSON round-trips and rejects NaN/infinity;
- Markdown escapes table/control characters correctly;
- HTML escapes hostile titles, identifiers, and annotations;
- plots reference stored evidence instead of recomputing it;
- plugin rules are never executed without explicit activation;
- golden reports are stable except for declared volatile metadata.
