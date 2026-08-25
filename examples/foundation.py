"""Exercise Lacuna's immutable result and scoped-configuration contracts."""

import lacuna as lc

with lc.config(threads=4, seed=42) as active:
    result = lc.AnalysisResult(
        metadata=lc.ResultMetadata(
            method="example.foundation",
            parameters={"threads": active.threads},
            seed=active.seed,
        ),
        metrics={"observations": 1_000},
        findings=(
            lc.Finding(
                code="EXAMPLE_COMPLETE",
                title="Example result is structured",
                message="This illustrative result exercises the public evidence contract.",
                state=lc.FindingState.PASS,
                severity=lc.Severity.INFO,
            ),
        ),
    )

print(result.to_json())
