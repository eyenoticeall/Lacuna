"""Deterministic renderers over immutable Lacuna audit evidence."""

from __future__ import annotations

import html
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import overload

from lacuna.exceptions import ReportError
from lacuna.types import AnalysisResult, Finding, JsonValue

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


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
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


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
    lines = [
        "# Lacuna audit",
        "",
        "## Summary",
        "",
        f"- Robustness score: **{_markdown_cell(score)} / 100**",
        f"- Evidence coverage: **{_markdown_cell(coverage)}**",
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
    score = _html_text(result.metrics.get("robustness_score"))
    coverage = _html_text(result.metrics.get("evidence_coverage"))
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
  <div class="summary">
    <div class="metric">Score<strong>{score} / 100</strong></div>
    <div class="metric">Evidence coverage<strong>{coverage}</strong></div>
  </div>
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

    @property
    def metrics(self) -> Mapping[str, JsonValue]:
        return self.result.metrics

    @property
    def findings(self) -> tuple[Finding, ...]:
        return self.result.findings

    def table(self, name: str) -> object:
        """Return a named source table."""

        return self.result.table(name)

    def summary(self) -> Mapping[str, JsonValue]:
        """Return the stable headline metrics used by every renderer."""

        names = (
            "robustness_score",
            "evidence_coverage",
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
    def to_html(self, path: None = None) -> str: ...

    @overload
    def to_html(
        self,
        path: str | os.PathLike[str],
        *,
        overwrite: bool = False,
    ) -> Path: ...

    def to_html(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        overwrite: bool = False,
    ) -> str | Path:
        """Return or safely persist escaped, self-contained HTML."""

        content = render_html(self.result)
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
        overwrite: bool = False,
    ) -> Path:
        """Persist JSON, Markdown, or HTML without silently overwriting files."""

        destination = Path(path)
        selected = (format or destination.suffix.lstrip(".")).lower()
        if selected in {"md", "markdown"}:
            content = render_markdown(self.result)
        elif selected == "html":
            content = render_html(self.result)
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
            evidence=evidence,
            provenance=provenance,
            invocation=invocation,
            overwrite=overwrite,
        )

    def __str__(self) -> str:
        return render_markdown(self.result)


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


__all__ = ["AuditReport", "render_html", "render_markdown"]
