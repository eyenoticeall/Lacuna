"""Deterministic renderers over immutable Lacuna audit evidence."""

from __future__ import annotations

import html
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, overload

from lacuna.exceptions import ReportError
from lacuna.types import AnalysisResult, Finding, JsonValue

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PLOTLY_RENDERER_VERSION = 1
_MAX_PANEL_ROWS = 10_000
ReportRenderer = Literal["core", "plotly"]
ReportView = Literal["auto", "audit", "signal", "portfolio", "event"]


def _json_ready(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_json_ready(item) for item in value]
    return value


def _plain(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, Mapping | Sequence) and not isinstance(value, str | bytes):
        return json.dumps(_json_ready(value), sort_keys=True, separators=(",", ":"))
    return str(value)


def _markdown_cell(value: object) -> str:
    text = _CONTROL_CHARACTERS.sub("", _plain(value))
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\n", "<br>")
    )


def _html_text(value: object) -> str:
    return html.escape(_CONTROL_CHARACTERS.sub("", _plain(value)))


def _table_rows(table: object) -> tuple[list[str], list[Mapping[str, object]]]:
    if not isinstance(table, list):
        return ["value"], [{"value": table}]
    if not table:
        return [], []
    if not all(isinstance(row, Mapping) for row in table):
        return ["value"], [{"value": value} for value in table]
    rows: list[Mapping[str, object]] = [
        {str(key): value for key, value in row.items()} for row in table
    ]
    columns = sorted({str(key) for row in rows for key in row})
    return columns, rows


def _markdown_table(table: object, *, limit: int = 50) -> str:
    columns, rows = _table_rows(table)
    if not rows:
        return "_No rows._"
    lines = [
        "| " + " | ".join(_markdown_cell(column) for column in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows[:limit]:
        lines.append(
            "| " + " | ".join(_markdown_cell(row.get(column)) for column in columns) + " |"
        )
    if len(rows) > limit:
        lines.append(f"\n_Showing {limit} of {len(rows)} rows._")
    return "\n".join(lines)


def _finding_markdown(finding: Finding) -> str:
    evidence = ""
    if finding.evidence:
        rendered = ", ".join(
            f"`{_markdown_cell(key)}`={_markdown_cell(value)}"
            for key, value in sorted(finding.evidence.items())
        )
        evidence = f"\n\nEvidence: {rendered}"
    return (
        f"### {finding.state.value} · {_markdown_cell(finding.title)}\n\n"
        f"- Code: `{_markdown_cell(finding.code)}`\n"
        f"- Severity: `{finding.severity.value}`\n"
        f"- Category: `{_markdown_cell(finding.category)}`\n\n"
        f"{_markdown_cell(finding.message)}{evidence}"
    )


def render_markdown(result: AnalysisResult) -> str:
    """Render an audit result without recomputing any evidence."""

    metrics = result.metrics
    score = metrics.get("robustness_score")
    coverage = metrics.get("evidence_coverage")
    if score is None:
        summary_lines = [
            "- Assessment model: **Categorical evidence profile — No universal score**",
            "- Required evidence coverage: "
            f"**{_markdown_cell(metrics.get('required_evidence_coverage', coverage))}**",
            "- Optional evidence coverage: "
            f"**{_markdown_cell(metrics.get('optional_evidence_coverage'))}**",
        ]
    else:
        summary_lines = [
            f"- Robustness score: **{_markdown_cell(score)} / 100**",
            f"- Evidence coverage: **{_markdown_cell(coverage)}**",
        ]
    lines = [
        "# Lacuna audit",
        "",
        "## Summary",
        "",
        *summary_lines,
        f"- Failures: **{_markdown_cell(metrics.get('failure_count'))}**",
        f"- Warnings: **{_markdown_cell(metrics.get('warning_count'))}**",
        f"- Unknown checks: **{_markdown_cell(metrics.get('unknown_count'))}**",
        f"- Not applicable: **{_markdown_cell(metrics.get('not_applicable_count'))}**",
        "",
        "## Findings",
        "",
    ]
    if result.findings:
        for finding in result.findings:
            lines.extend([_finding_markdown(finding), ""])
    else:
        lines.extend(["_No findings._", ""])
    lines.extend(["## Evidence tables", ""])
    for name in sorted(result.tables):
        lines.extend(
            [
                f"### {_markdown_cell(name.replace('_', ' ').title())}",
                "",
                _markdown_table(result.table(name)),
                "",
            ]
        )
    lines.extend(
        [
            "## Methodology and provenance",
            "",
            f"- Method: `{_markdown_cell(result.metadata.method)}`",
            f"- Method version: `{result.metadata.method_version}`",
            f"- Schema version: `{_markdown_cell(result.schema_version)}`",
            f"- Created at: `{_markdown_cell(result.metadata.created_at)}`",
            f"- Parameters: `{_markdown_cell(result.metadata.parameters)}`",
        ]
    )
    if result.warnings:
        lines.extend(["", "### Method warnings", ""])
        lines.extend(f"- {_markdown_cell(warning)}" for warning in result.warnings)
    return "\n".join(lines).rstrip() + "\n"


def _html_table(table: object, *, limit: int = 50) -> str:
    columns, rows = _table_rows(table)
    if not rows:
        return "<p><em>No rows.</em></p>"
    head = "".join(f"<th>{_html_text(column)}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_html_text(row.get(column))}</td>" for column in columns) + "</tr>"
        for row in rows[:limit]
    )
    note = f"<p><em>Showing {limit} of {len(rows)} rows.</em></p>" if len(rows) > limit else ""
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{note}"


def render_html(result: AnalysisResult) -> str:
    """Render a self-contained escaped HTML report from stored evidence."""

    findings = "".join(
        (
            "<article class='finding'>"
            f"<h3>{_html_text(finding.state.value)} · {_html_text(finding.title)}</h3>"
            f"<p><strong>{_html_text(finding.code)}</strong> · "
            f"{_html_text(finding.severity.value)} · {_html_text(finding.category)}</p>"
            f"<p>{_html_text(finding.message)}</p>"
            f"<pre>{_html_text(json.dumps(finding.to_dict()['evidence'], sort_keys=True))}</pre>"
            "</article>"
        )
        for finding in result.findings
    )
    tables = "".join(
        f"<section><h3>{_html_text(name.replace('_', ' ').title())}</h3>"
        f"{_html_table(result.table(name))}</section>"
        for name in sorted(result.tables)
    )
    raw_score = result.metrics.get("robustness_score")
    coverage = _html_text(result.metrics.get("evidence_coverage"))
    if raw_score is None:
        summary = (
            "<div class='metric'>Assessment<strong>No universal score</strong></div>"
            "<div class='metric'>Required evidence coverage"
            f"<strong>{_html_text(result.metrics.get('required_evidence_coverage', coverage))}"
            "</strong></div>"
            "<div class='metric'>Optional evidence coverage"
            f"<strong>{_html_text(result.metrics.get('optional_evidence_coverage'))}</strong></div>"
        )
    else:
        score = _html_text(raw_score)
        summary = (
            f"<div class='metric'>Score<strong>{score} / 100</strong></div>"
            f"<div class='metric'>Evidence coverage<strong>{coverage}</strong></div>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lacuna audit</title>
  <style>
    :root {{ color-scheme: dark; font-family: ui-sans-serif, system-ui, sans-serif; }}
    body {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 3rem 1.25rem;
      background: #0b0d0e;
      color: #eef2f1;
    }}
    h1, h2, h3 {{ line-height: 1.15; }}
    .summary {{ display: flex; gap: 1rem; flex-wrap: wrap; }}
    .metric, .finding, section {{
      background: #15191a;
      border: 1px solid #293132;
      border-radius: .75rem;
      padding: 1rem;
      margin: 1rem 0;
    }}
    .metric strong {{ display: block; color: #55d6be; font-size: 1.6rem; }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-variant-numeric: tabular-nums;
    }}
    th, td {{ border-bottom: 1px solid #293132; padding: .55rem; text-align: left; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; color: #b8c4c2; }}
  </style>
</head>
<body>
  <header>
    <h1>Lacuna audit</h1>
    <p>Structured quantitative research evidence.</p>
  </header>
  <div class="summary">{summary}</div>
  <h2>Findings</h2>{findings or "<p><em>No findings.</em></p>"}
  <h2>Evidence tables</h2>{tables}
  <h2>Provenance</h2>
  <pre>{_html_text(json.dumps(result.metadata.to_dict(), indent=2, sort_keys=True))}</pre>
</body>
</html>
"""


@dataclass(frozen=True, slots=True)
class AuditReport:
    """Immutable audit evidence with deterministic renderers."""

    result: AnalysisResult
    evidence: Mapping[str, AnalysisResult] = field(default_factory=dict)

    def __post_init__(self) -> None:
        retained: dict[str, AnalysisResult] = {}
        for name, result in sorted(self.evidence.items()):
            if not isinstance(name, str) or not name:
                raise ReportError("evidence names must be non-empty strings")
            if name == "audit":
                raise ReportError("the evidence source name 'audit' is reserved")
            if not isinstance(result, AnalysisResult):
                raise ReportError("named evidence values must be AnalysisResult instances")
            retained[name] = result
        object.__setattr__(self, "evidence", MappingProxyType(retained))

    @property
    def metrics(self) -> Mapping[str, JsonValue]:
        return self.result.metrics

    @property
    def findings(self) -> tuple[Finding, ...]:
        return self.result.findings

    def table(self, name: str, source: str | None = None) -> object:
        """Return one stored table, rejecting ambiguous unqualified names."""

        if source is not None:
            if source == "audit":
                selected = self.result
            else:
                try:
                    selected = self.evidence[source]
                except KeyError as error:
                    raise ReportError(f"unknown evidence source: {source!r}") from error
            try:
                return selected.table(name)
            except KeyError as error:
                raise ReportError(f"source {source!r} has no table {name!r}") from error

        matches: list[tuple[str, AnalysisResult]] = []
        if name in self.result.tables:
            matches.append(("audit", self.result))
        matches.extend(
            (evidence_name, evidence)
            for evidence_name, evidence in self.evidence.items()
            if name in evidence.tables
        )
        if not matches:
            raise ReportError(f"no stored evidence contains table {name!r}")
        if len(matches) > 1:
            sources = ", ".join(source_name for source_name, _ in matches)
            raise ReportError(
                f"table {name!r} is ambiguous across sources {sources}; pass source explicitly"
            )
        return matches[0][1].table(name)

    def summary(self) -> Mapping[str, JsonValue]:
        """Return the stable headline metrics used by every renderer."""

        names = (
            "robustness_score",
            "evidence_coverage",
            "required_evidence_coverage",
            "optional_evidence_coverage",
            "required_evidence_complete",
            "failure_count",
            "warning_count",
            "unknown_count",
            "not_applicable_count",
        )
        return MappingProxyType(
            {name: self.result.metrics[name] for name in names if name in self.result.metrics}
        )

    @overload
    def to_json(self, path: None = None, *, indent: int | None = 2) -> str: ...

    @overload
    def to_json(
        self,
        path: str | os.PathLike[str],
        *,
        indent: int | None = 2,
        overwrite: bool = False,
    ) -> Path: ...

    def to_json(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        indent: int | None = 2,
        overwrite: bool = False,
    ) -> str | Path:
        """Return or safely persist the canonical machine-readable report."""

        content = self.result.to_json(indent=indent)
        if path is None:
            return content
        return _write_content(path, content + "\n", overwrite=overwrite)

    @overload
    def to_markdown(self, path: None = None) -> str: ...

    @overload
    def to_markdown(
        self,
        path: str | os.PathLike[str],
        *,
        overwrite: bool = False,
    ) -> Path: ...

    def to_markdown(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        overwrite: bool = False,
    ) -> str | Path:
        """Return or safely persist review-friendly Markdown."""

        content = render_markdown(self.result)
        if path is None:
            return content
        return _write_content(path, content, overwrite=overwrite)

    @overload
    def to_html(
        self,
        path: None = None,
        *,
        renderer: ReportRenderer = "core",
        view: ReportView = "auto",
    ) -> str: ...

    @overload
    def to_html(
        self,
        path: str | os.PathLike[str],
        *,
        renderer: ReportRenderer = "core",
        view: ReportView = "auto",
        overwrite: bool = False,
    ) -> Path: ...

    def to_html(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        renderer: ReportRenderer = "core",
        view: ReportView = "auto",
        overwrite: bool = False,
    ) -> str | Path:
        """Return or safely persist core or evidence-native Plotly HTML."""

        if renderer == "core":
            content = render_html(self.result)
        elif renderer == "plotly":
            content = render_plotly_html(self, view=view)
        else:
            raise ReportError("HTML renderer must be 'core' or 'plotly'")
        if path is None:
            return content
        return _write_content(path, content, overwrite=overwrite)

    def show(self) -> None:
        """Print a text report without color or interactive side effects."""

        print(self.to_markdown(), end="")

    def write(
        self,
        path: str | os.PathLike[str],
        *,
        format: str | None = None,
        renderer: ReportRenderer = "core",
        view: ReportView = "auto",
        overwrite: bool = False,
    ) -> Path:
        """Persist JSON, Markdown, or HTML without silently overwriting files."""

        destination = Path(path)
        selected = (format or destination.suffix.lstrip(".")).lower()
        if selected in {"md", "markdown"}:
            content = render_markdown(self.result)
        elif selected == "html":
            if renderer == "core":
                content = render_html(self.result)
            elif renderer == "plotly":
                content = render_plotly_html(self, view=view)
            else:
                raise ReportError("HTML renderer must be 'core' or 'plotly'")
        elif selected == "json":
            content = self.result.to_json() + "\n"
        else:
            raise ReportError("report format must be json, md/markdown, or html")
        return _write_content(destination, content, overwrite=overwrite)

    def bundle(
        self,
        path: str | os.PathLike[str],
        *,
        configuration: Mapping[str, object] | None = None,
        evidence: Mapping[str, AnalysisResult] | None = None,
        provenance: Mapping[str, object] | None = None,
        invocation: Mapping[str, object] | None = None,
        overwrite: bool = False,
    ) -> Path:
        """Persist a deterministic, checksummed, non-executable evidence bundle."""

        from lacuna.bundle import create_bundle

        return create_bundle(
            self,
            path,
            configuration=configuration,
            evidence=self.evidence if evidence is None else evidence,
            provenance=provenance,
            invocation=invocation,
            overwrite=overwrite,
        )

    def __str__(self) -> str:
        return render_markdown(self.result)


def _plot_value(value: object) -> object:
    if isinstance(value, str):
        return html.escape(_CONTROL_CHARACTERS.sub("", value), quote=True)
    return value


def _plot_rows(table: object) -> list[Mapping[str, object]]:
    if not isinstance(table, list) or not all(isinstance(row, Mapping) for row in table):
        return []
    return [{str(key): _plot_value(value) for key, value in row.items()} for row in table]


def _resolved_view(report: AuditReport, view: ReportView) -> ReportView:
    if view != "auto":
        return view
    methods = {result.metadata.method for result in report.evidence.values()}
    if any(method.startswith("events.") for method in methods):
        return "event"
    if any(method.startswith("signal.portfolio_projection") for method in methods):
        return "portfolio"
    if any(method.startswith(("signal.", "labels.")) for method in methods):
        return "signal"
    return "audit"


def render_plotly_html(report: AuditReport, *, view: ReportView = "auto") -> str:
    """Render deterministic interactive panels from retained rows only."""

    if view not in {"auto", "audit", "signal", "portfolio", "event"}:
        raise ReportError("report view must be auto, audit, signal, portfolio, or event")
    try:
        import jinja2
        import plotly.graph_objects as go  # type: ignore[import-untyped]
        import plotly.io as pio  # type: ignore[import-untyped]
    except ImportError as error:
        raise ReportError(
            "the Plotly renderer requires the 'report' extra; install lacuna[report]"
        ) from error

    selected_view = _resolved_view(report, view)
    figures: list[tuple[str, str, str, str, str]] = []
    notices: list[str] = []
    audit_figure = go.Figure()
    audit_fields = (
        "evidence_coverage",
        "required_evidence_coverage",
        "optional_evidence_coverage",
    )
    audit_values = [report.metrics.get(field) for field in audit_fields]
    if any(isinstance(value, int | float) for value in audit_values):
        audit_figure.add_bar(
            x=[field.replace("_", " ") for field in audit_fields],
            y=[value if isinstance(value, int | float) else 0.0 for value in audit_values],
            name="coverage",
        )
    states: dict[str, int] = {}
    for finding in report.findings:
        states[finding.state.value] = states.get(finding.state.value, 0) + 1
    if states:
        audit_figure.add_bar(
            x=sorted(states), y=[states[key] for key in sorted(states)], name="findings"
        )
    audit_figure.update_layout(
        title="Audit coverage and findings",
        template="plotly_dark",
        barmode="group",
        meta={
            "source": "audit",
            "table": None,
            "fields": (*audit_fields, "finding.state"),
            "renderer_version": _PLOTLY_RENDERER_VERSION,
        },
    )
    figures.append(("Audit coverage and findings", "audit", "metrics/findings", "", "audit"))

    specifications = (
        ("IC by period", "ic_by_period", "observation_time", ("ic",), "line"),
        ("IC by horizon", "ic_by_horizon", "horizon", ("mean_ic",), "line"),
        (
            "Bucket returns",
            "bucket_returns",
            "bucket",
            ("mean_return",),
            "bar",
        ),
        (
            "Quantile returns",
            "quantile_returns",
            "quantile",
            ("mean_return",),
            "bar",
        ),
        (
            "Top-minus-bottom spread",
            "spread_by_period",
            "observation_time",
            ("spread",),
            "line",
        ),
        (
            "Bucket spread",
            "bucket_spread_by_period",
            "observation_time",
            ("spread",),
            "line",
        ),
        (
            "Turnover and autocorrelation by lag",
            "turnover_by_lag",
            "lag",
            ("mean_rank_turnover", "mean_signal_autocorrelation"),
            "line",
        ),
        (
            "IC decay",
            "ic_decay",
            "horizon",
            ("mean_ic", "mean_top_bottom_spread"),
            "line",
        ),
        (
            "Data attrition",
            "data_attrition",
            "stage",
            ("excluded_fraction",),
            "bar",
        ),
        (
            "Portfolio cohort returns",
            "cohort_returns",
            "observation_time",
            ("portfolio_return",),
            "line",
        ),
        (
            "Event response",
            "event_response",
            "offset",
            ("mean_response", "lower", "upper"),
            "line",
        ),
    )
    sources = (("audit", report.result), *tuple(report.evidence.items()))
    plot_figures: list[object] = [audit_figure]
    for source_name, result in sources:
        method = result.metadata.method
        source_view: ReportView = (
            "event"
            if method.startswith("events.")
            else "portfolio"
            if method.startswith("signal.portfolio_projection")
            else "signal"
            if method.startswith(("signal.", "labels."))
            else "audit"
        )
        if selected_view != "audit" and source_view not in {selected_view, "audit"}:
            continue
        if selected_view == "audit" and source_name != "audit":
            continue
        for title, table_name, x_field, y_fields, kind in specifications:
            if table_name not in result.tables:
                continue
            rows = _plot_rows(result.table(table_name))
            if len(rows) > _MAX_PANEL_ROWS:
                notices.append(
                    f"Omitted {source_name}.{table_name}: {len(rows)} rows exceed "
                    f"the {_MAX_PANEL_ROWS}-row renderer limit; no sampling was performed."
                )
                continue
            available_y = tuple(field for field in y_fields if any(field in row for row in rows))
            if not rows or not available_y or not any(x_field in row for row in rows):
                continue
            figure = go.Figure()
            x_values = [row.get(x_field) for row in rows]
            for y_field in available_y:
                y_values = [row.get(y_field) for row in rows]
                if kind == "bar":
                    figure.add_bar(x=x_values, y=y_values, name=y_field)
                else:
                    figure.add_scatter(
                        x=x_values,
                        y=y_values,
                        mode="lines+markers",
                        name=y_field,
                    )
            configuration = {
                "kind": kind,
                "x": x_field,
                "y": available_y,
                "row_policy": "all_stored_rows",
            }
            figure.update_layout(
                title=title,
                template="plotly_dark",
                meta={
                    "source": source_name,
                    "table": table_name,
                    "fields": (x_field, *available_y),
                    "renderer_version": _PLOTLY_RENDERER_VERSION,
                    "plotting_configuration": configuration,
                },
            )
            plot_figures.append(figure)
            figures.append(
                (
                    title,
                    source_name,
                    table_name,
                    json.dumps(configuration, sort_keys=True, separators=(",", ":")),
                    source_view,
                )
            )

    rendered_panels: list[dict[str, object]] = []
    for index, (figure, details) in enumerate(zip(plot_figures, figures, strict=True), start=1):
        panel_title, panel_source, panel_table, config_text, panel_view = details
        identifier = f"lacuna-panel-{index:02d}"
        chart = pio.to_html(
            figure,
            include_plotlyjs=index == 1,
            full_html=False,
            div_id=identifier,
            config={"displaylogo": False, "responsive": True},
        )
        rendered_panels.append(
            {
                "title": panel_title,
                "source": panel_source,
                "table": panel_table,
                "configuration": config_text,
                "view": panel_view,
                "identifier": identifier,
                "chart": chart,
            }
        )

    environment = jinja2.Environment(autoescape=True, undefined=jinja2.StrictUndefined)
    template = environment.from_string(
        """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lacuna evidence report</title>
<style>
:root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
body { margin: 0; background: #090d0d; color: #e9f1ef; }
.shell { max-width: 1180px; margin: auto; padding: 3rem 1.25rem; }
header { border-bottom: 1px solid #243231; margin-bottom: 2rem; }
.eyebrow { color: #62d8be; text-transform: uppercase; letter-spacing: .14em; font-size: .75rem; }
.panel, .notice {
  background: #111817; border: 1px solid #263634; border-radius: 16px;
  padding: 1rem; margin: 1rem 0;
}
.trace { color: #9bb0ac; font-size: .8rem; overflow-wrap: anywhere; }
code { color: #b8ebe0; }
</style>
</head>
<body>
<main class="shell">
<header>
<p class="eyebrow">Lacuna · stored evidence</p>
<h1>{{ view|title }} report</h1>
<p>Interactive views render retained result rows without recalculation or sampling.</p>
</header>
{% for notice in notices %}
<aside class="notice">{{ notice }}</aside>
{% endfor %}
{% for panel in panels %}
<section class="panel"
         data-source="{{ panel.source }}"
         data-table="{{ panel.table }}"
         data-view="{{ panel.view }}">
<h2>{{ panel.title }}</h2>
<p class="trace">
Source <code>{{ panel.source }}</code> · Table <code>{{ panel.table }}</code>
{% if panel.configuration %}
· Configuration <code>{{ panel.configuration }}</code>
{% endif %}
· Renderer v{{ renderer_version }}
</p>
<!--CHART:{{ panel.identifier }}-->
</section>
{% endfor %}
</main></body></html>"""
    )
    rendered = template.render(
        view=selected_view,
        notices=notices,
        panels=rendered_panels,
        renderer_version=_PLOTLY_RENDERER_VERSION,
    )
    for panel in rendered_panels:
        rendered = rendered.replace(
            f"<!--CHART:{panel['identifier']}-->",
            str(panel["chart"]),
            1,
        )
    return rendered + "\n"


def _write_content(
    path: str | os.PathLike[str],
    content: str,
    *,
    overwrite: bool,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    try:
        with destination.open(mode, encoding="utf-8", newline="\n") as output:
            output.write(content)
    except FileExistsError as error:
        raise ReportError(f"refusing to overwrite existing report: {destination}") from error
    return destination


__all__ = [
    "AuditReport",
    "ReportRenderer",
    "ReportView",
    "render_html",
    "render_markdown",
    "render_plotly_html",
]
