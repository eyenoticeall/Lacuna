# Methodology principles

Every future statistic should expose its method, parameters, assumptions, sample size, seed, input fingerprint, and warning state. Computation produces a versioned result object before a renderer produces Markdown, HTML, or a chart.

The initial contracts encode two important distinctions:

- A finding's outcome (`PASS`, `WARN`, `FAIL`, `UNKNOWN`, or `NOT_APPLICABLE`) is separate from its severity.
- Missing evidence is represented as `UNKNOWN`; it is never silently promoted to `PASS`.

Method-specific pages will include formulas, assumptions, reference comparisons, numerical tolerances, and situations where a method should not be used before that method is considered complete.

For implementation-level requirements, see [Contributing a method](../development/contributing-a-method.md), [Testing strategy](../development/testing.md), and the relevant [subsystem guide](../subsystems/financial-validation.md).
