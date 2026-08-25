# Methodology principles

Every statistic exposes its method, parameters, assumptions, sample size, seed where applicable, input
fingerprint when available, and warning state. Computation produces a versioned result object before a
renderer produces Markdown, HTML, or a chart.

The initial contracts encode two important distinctions:

- A finding's outcome (`PASS`, `WARN`, `FAIL`, `UNKNOWN`, or `NOT_APPLICABLE`) is separate from its severity.
- Missing evidence is represented as `UNKNOWN`; it is never silently promoted to `PASS`.

The implemented v0.1 methods are documented in:

- [Forward-return labels](forward-returns.md)
- [Information coefficient](information-coefficient.md)
- [Quantiles, turnover, and decay](quantiles-turnover-decay.md)
- [Walk-forward validation, purging, and embargo](temporal-validation.md)
- [Bootstrap inference](bootstrap.md)
- [Audit findings and score](audit-scoring.md)

The implemented v0.2 methods are documented in:

- [Experiment lineage and multiple testing](experiments-multiple-testing.md)
- [Parameter, temporal, and universe robustness](robustness-analysis.md)
- [Regime classification and conditional evidence](regime-analysis.md)

For implementation-level requirements, see [Contributing a method](../development/contributing-a-method.md), [Testing strategy](../development/testing.md), and the relevant [subsystem guide](../subsystems/financial-validation.md).
