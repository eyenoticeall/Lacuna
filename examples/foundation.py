"""Exercise Lacuna's initial configuration and result contracts."""

import lacuna as lc

with lc.config(threads=4, seed=42) as active:
    result = lc.AnalysisResult(
        metadata=lc.ResultMetadata(
            method="example.foundation",
            parameters={"threads": active.threads},
            seed=active.seed,
        ),
        metrics={"observations": 0},
        findings=(
            lc.Finding(
                code="FOUNDATION_ONLY",
                title="Analytical modules are not implemented yet",
                message="This repository currently contains the Phase 0 foundation.",
                state=lc.FindingState.UNKNOWN,
                severity=lc.Severity.INFO,
            ),
        ),
    )

print(result.to_json())
