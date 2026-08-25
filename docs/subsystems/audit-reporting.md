# Audit engine and reporting

**Status:** the rule protocol, explicit unknown states, versioned scoring, and deterministic JSON/Markdown output are v0.1 contracts. Rich HTML, plotting, and interactive exploration arrive later.

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
    rule_version: str

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

## Markdown and terminal output

Markdown should optimize for code review and issue attachment:

1. identity and reproducibility summary;
2. decision summary and evidence coverage;
3. failures and warnings;
4. unknown or unavailable checks;
5. key evidence tables;
6. methodology and provenance appendix.

Terminal output is a compact view of the same data and uses text labels in addition to color. `--no-color` must be supported. Exit-code behavior belongs to the CLI contract and should distinguish execution failure from an audit containing failed findings.

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
