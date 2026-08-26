from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lacuna.report import AuditReport
from lacuna.types import AnalysisResult, ResultMetadata

pytestmark = pytest.mark.optional_dependency(
    reason="real Chromium report rendering requires the pinned browser-qa dependency group"
)

MANIFEST_PATH = Path(__file__).parents[1] / "fixtures" / "plotly-browser-v1.json"


def _report() -> AuditReport:
    audit = AnalysisResult(
        metadata=ResultMetadata(
            method="audit.browser_smoke",
            created_at=datetime(2026, 8, 26, tzinfo=UTC),
        ),
        metrics={"evidence_coverage": 1.0, "warning_count": 0, "failure_count": 0},
    )
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="signal.ic",
            created_at=datetime(2026, 8, 26, tzinfo=UTC),
        ),
        metrics={"mean_ic": 0.15},
        tables={
            "ic_by_period": (
                {"observation_time": "2026-01-02", "horizon": "1D", "ic": 0.1},
                {"observation_time": "2026-01-03", "horizon": "1D", "ic": 0.2},
            ),
            "data_attrition": (
                {
                    "stage": "alignment",
                    "reason": "missing_label",
                    "input_rows": 100,
                    "retained_rows": 98,
                    "excluded_rows": 2,
                    "excluded_fraction": 0.02,
                    "policy": "drop_with_evidence",
                },
            ),
        },
    )
    return AuditReport(audit, evidence={"ic": evidence})


def test_plotly_report_renders_in_pinned_chromium(tmp_path: Path) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    viewport = manifest["viewport"]
    output_root = Path(os.environ.get("LACUNA_BROWSER_ARTIFACT_DIR", tmp_path))
    output_root.mkdir(parents=True, exist_ok=True)
    screenshot = output_root / manifest["artifact"]
    page_errors: list[str] = []
    external_requests: list[str] = []

    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": viewport["width"], "height": viewport["height"]},
            device_scale_factor=manifest["device_scale_factor"],
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "request",
            lambda request: (
                external_requests.append(request.url)
                if request.url.startswith(("http://", "https://"))
                else None
            ),
        )
        page.set_content(_report().to_html(renderer="plotly", view="signal"), wait_until="load")
        page.wait_for_function(
            "document.querySelectorAll('.js-plotly-plot').length === 3",
            timeout=15_000,
        )

        observed = page.locator("section.panel").evaluate_all(
            """panels => panels.map(panel => ({
                id: panel.querySelector('.js-plotly-plot').id,
                source: panel.dataset.source,
                table: panel.dataset.table
            }))"""
        )
        for panel in page.locator(".js-plotly-plot").all():
            box = panel.bounding_box()
            assert box is not None
            assert box["width"] > 100
            assert box["height"] > 100
        page.screenshot(path=str(screenshot), full_page=True, animations="disabled")
        browser.close()

    assert observed == manifest["panels"]
    assert page_errors == []
    assert external_requests == []
    assert screenshot.stat().st_size > 10_000
