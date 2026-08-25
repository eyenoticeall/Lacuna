from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from lacuna.exceptions import ReportError
from lacuna.report import AuditReport
from lacuna.types import AnalysisResult, Finding, FindingState, ResultMetadata, Severity


def _report() -> AuditReport:
    finding = Finding(
        code="HOSTILE|CODE",
        title="bad | title\n<script>alert(1)</script>",
        message="source says <img src=x onerror=alert(1)>\x00",
        state=FindingState.WARN,
        severity=Severity.HIGH,
        category="data|integrity",
        evidence={"nested": {"b": 2, "a": (1, "x|y")}},
    )
    return AuditReport(
        AnalysisResult(
            metadata=ResultMetadata(
                method="audit.test",
                created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                parameters={"z": 2, "a": {"nested": True}},
            ),
            metrics={
                "robustness_score": 50.0,
                "evidence_coverage": 0.75,
                "failure_count": 0,
                "warning_count": 1,
                "unknown_count": 0,
                "not_applicable_count": 0,
            },
            findings=(finding,),
            tables={"hostile_table": ({"cell": "x|y\nz\x00", "number": 1.23456789},)},
        )
    )


def test_json_round_trips_and_summary_is_stable() -> None:
    report = _report()
    payload = json.loads(report.to_json())

    assert payload["schema_version"] == "1"
    assert payload["findings"][0]["state"] == "WARN"
    assert report.summary()["robustness_score"] == 50.0
    assert report.to_json() == report.to_json()


def test_markdown_escapes_tables_and_removes_control_characters() -> None:
    markdown = _report().to_markdown()

    assert "bad \\| title<br><script>alert(1)</script>" in markdown
    assert "x\\|y<br>z" in markdown
    assert "\x00" not in markdown
    assert markdown == _report().to_markdown()


def test_html_escapes_hostile_source_text_and_is_self_contained() -> None:
    rendered = _report().to_html()

    assert "<script>alert(1)</script>" not in rendered
    assert "<img src=x onerror=alert(1)>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert "\x00" not in rendered
    assert "http://" not in rendered
    assert "https://" not in rendered


def test_report_writes_safely_and_supports_direct_renderer_paths(tmp_path: object) -> None:
    root = tmp_path  # type: ignore[assignment]
    report = _report()
    markdown_path = root / "nested" / "audit.md"
    html_path = root / "audit.html"
    json_path = root / "audit.json"

    assert report.to_markdown(markdown_path) == markdown_path
    assert report.to_html(html_path) == html_path
    assert report.to_json(json_path) == json_path
    assert markdown_path.read_text(encoding="utf-8") == report.to_markdown()
    assert html_path.read_text(encoding="utf-8") == report.to_html()
    assert json.loads(json_path.read_text(encoding="utf-8"))["schema_version"] == "1"

    with pytest.raises(ReportError, match="refusing to overwrite"):
        report.write(markdown_path)
    report.write(markdown_path, overwrite=True)


def test_show_prints_plain_markdown(capsys: object) -> None:
    report = _report()
    report.show()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out == report.to_markdown()
    assert "\x1b[" not in captured.out
