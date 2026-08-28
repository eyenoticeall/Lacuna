# Public API compatibility

Lacuna `0.14` preserves the complete `0.13` Python API while changing only private implementation,
performance, and release evidence. Users install `lacuna-quant`, then continue to use
`import lacuna` and the `lacuna` command. The `0.14` fixture declares no new imports and inherits
every `0.1` through `0.13` contract, so CI detects accidental removal, export, or signature drift.

## Supported surface

The supported top-level workflow is:

```python
import lacuna as lc

study = lc.SignalStudy(signal=signal, prices=prices)
report = study.audit()
```

The following modules are part of the supported core contract through `0.14`:

| Module | Supported purpose |
| --- | --- |
| `lacuna.labels` | Forward-return labels and `LabelResult` |
| `lacuna.signal` | IC, buckets, neutralization, turnover, decay inference, and diagnostic projection |
| `lacuna.events` | Availability-anchored event paths and clustered response inference |
| `lacuna.cv` | Walk-forward, purged K-fold, and CPCV split/path evidence |
| `lacuna.validation` | Bootstrap/permutation, Sharpe/PBO, Reality Check/SPA, parameter surfaces, and multiplicity correction |
| `lacuna.experiment` | Canonical fingerprints and append-only experiment/selection lineage |
| `lacuna.robustness` | Continuous, subperiod, and timestamped-universe perturbation |
| `lacuna.regime` | Point-in-time-aware classification and conditional regime evidence |
| `lacuna.costs` | Composable cost estimates, stress/break-even analysis, liquidity diagnostics, and capacity curves |
| `lacuna.bias` | Safe as-of joins, future/revision checks, survivorship, membership, universe drift, and dataset contracts |
| `lacuna.audit` | Rule evaluation and audit assembly |
| `lacuna.audit_profiles` | Versioned cross-phase profiles, categorical coverage, and source-finding propagation |
| `lacuna.report` | JSON, Markdown, core HTML, and optional evidence-native Plotly rendering |
| `lacuna.bundle` | Deterministic evidence bundles, strict standalone manifest reads, and non-executing integrity verification |
| `lacuna.adapters` | Physical normalization, factor panels, DuckDB/sklearn interop, and declared vendor/backtest schemas |
| `lacuna.plugins` | Metadata-only discovery, selection, protocol negotiation, and explicit trusted activation |
| `lacuna.benchmark` | Reproducible developer benchmark services |
| `lacuna.diagnostics` | Versioned, non-invasive installation and runtime health evidence |
| `lacuna.schemas` | Packaged machine-readable result, bundle, profile, and compatibility contracts |

Names declared by each module's `__all__`, the package-root exports, and the primary callable
signatures are captured in the versioned files under `tests/fixtures/public-api-v*.json`. Contract
tests verify that `0.14` adds no import surface. Separate tests require every `v0.1` through `v0.13`
root/module export and compatible primary signature to remain available.

The [complete Python API surface](python-api-surface.md) lists every root and supported-module
export with its semantic documentation route. Its
[coverage manifest](public-reference-coverage-v1.json) is checked against the running package and
the cumulative fixtures, so compatibility coverage and reference coverage cannot drift silently.

`lacuna-options` is a separate distribution and import package. Its initial exact exports and
signatures live in `extensions/lacuna-options/tests/fixtures/public-api-v0.1.json`; the `v0.2`
fixture inherits them unchanged while recording the new `lacuna-quant` dependency line. Extension
versions remain independent of core `0.13.x` and `0.14.x` versions.

## Compatibility promise

Within the respective core `0.14.x` and extension `0.2.x` release lines:

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

Because Lacuna is pre-1.0, a future minor release may intentionally change the public contract. Such a change
must update the fixture, changelog, documentation, and migration guidance in the same review.

An extension dependency-range change is also a compatibility decision. Publishing core and an
extension in one GitHub Release does not make their version numbers or public contracts identical.

## Reviewing an intentional change

1. Explain whether the change is additive, deprecated, or breaking.
2. Update the affected method, schema, rule, or score version independently.
3. Add migration guidance when existing user code or persisted evidence is affected.
4. Update the public contract fixture only after the implementation and documentation agree.
5. Run the contract tests through the minimum and newest supported Python versions.
