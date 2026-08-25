# Public API compatibility

Lacuna `0.1` publishes an explicit Python API contract even though the project remains pre-1.0.
The contract makes release-candidate review concrete: users can distinguish supported entry points
from implementation details, and CI detects accidental export or signature drift.

## Supported surface

The supported top-level workflow is:

```python
import lacuna as lc

study = lc.SignalStudy(...)
report = study.audit()
```

The following modules are part of the `0.1` contract:

| Module | Supported purpose |
| --- | --- |
| `lacuna.labels` | Forward-return labels and `LabelResult` |
| `lacuna.signal` | IC, quantiles, turnover, and decay |
| `lacuna.cv` | Walk-forward and purged splitters |
| `lacuna.validation` | Deterministic bootstrap inference |
| `lacuna.audit` | Rule evaluation and audit assembly |
| `lacuna.report` | JSON, Markdown, and HTML rendering |
| `lacuna.adapters` | Physical normalization helpers |
| `lacuna.benchmark` | Reproducible developer benchmark services |

Names declared by each module's `__all__`, the package-root exports, and the primary callable
signatures are captured in `tests/fixtures/public-api-v0.1.json`. Contract tests compare the running
package with that reviewed fixture.

## Compatibility promise

Within the `0.1.x` release line:

- exported names are not removed or renamed without a deprecation path;
- required parameters are not added to an existing call;
- parameter defaults and keyword-only boundaries do not change silently;
- result-envelope compatibility remains governed independently by `schema_version`;
- statistical meaning remains governed independently by each `method_version`;
- finding codes and audit rule versions remain stable or receive explicit migration notes;
- bug fixes may reject input that never satisfied the documented semantic contract.

Additive optional APIs can appear in a minor or patch release when they do not change existing
behavior. A value-affecting method correction increments its method version even when the Python
signature does not change.

## Outside the contract

Names beginning with `_`, including `lacuna._native`, are internal implementation details. The raw
native functions are exercised by packaging smoke tests but are not a substitute for the validated
Python services. Undocumented imports from implementation modules have no compatibility promise.

Because Lacuna is pre-1.0, a future `0.2` may intentionally change the public contract. Such a change
must update the fixture, changelog, documentation, and migration guidance in the same review.

## Reviewing an intentional change

1. Explain whether the change is additive, deprecated, or breaking.
2. Update the affected method, schema, rule, or score version independently.
3. Add migration guidance when existing user code or persisted evidence is affected.
4. Update the public contract fixture only after the implementation and documentation agree.
5. Run the contract tests through the minimum and newest supported Python versions.
