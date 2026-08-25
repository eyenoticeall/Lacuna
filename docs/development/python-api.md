# Python API design

Python is Lacuna's public language. It owns usability, semantic validation, explicit configuration, backend dispatch, error translation, and structured result construction.

## Functional API first

Every analytical capability starts with a composable function:

```python
result = lc.signal.ic(
    signal,
    forward_returns,
    method="spearman",
    by="date",
)
```

The function is the canonical behavior. Higher-level study objects delegate to it instead of maintaining an independent implementation.

## Study API second

Study objects coordinate shared normalized inputs and repeated analyses:

```python
study = lc.SignalStudy(
    signal=signal,
    prices=prices,
    signal_time="date",
    price_time="date",
    instrument="instrument",
    horizons=("1D", "5D", "20D"),
    price_adjustment="total_return_adjusted",
)
```

A study may cache immutable derived data only after it has a stable fingerprint. It must not conceal changed inputs, defaults, random state, or execution assumptions.

Study methods return the same domain result types as functional calls. The study is orchestration, not a second domain layer.

## Public function pipeline

Use this sequence consistently:

```text
resolve arguments and scoped config
              ↓
normalize supported edge input
              ↓
validate semantic schema and policies
              ↓
select reference/Polars/native execution
              ↓
assemble typed result and provenance
              ↓
return without presentation side effects
```

Avoid functions that accept arbitrary `**kwargs`. Configuration objects or explicit keyword-only parameters make defaults type-checkable and serializable.

## Naming rules

- Names describe evidence, not marketing conclusions: `mean_ic`, not `signal_quality`.
- Unit-bearing values include units where ambiguity exists: `spread_bps`, `holding_days`.
- Time columns use semantic names: `available_time`, not `date2`.
- Booleans name the positive condition: `include_delisting_returns`.
- Method selectors are stable lowercase strings or enums with documented values.
- `by` identifies grouping keys; `time` and `instrument` resolve semantic columns.

## Progressive disclosure

Simple valid calls should be short, while risky assumptions remain inspectable:

```python
lc.audit(results={"ic": ic_result, "bootstrap": bootstrap_result})
```

An advanced method exposes its model explicitly:

```python
lc.validation.bootstrap(
    returns,
    method="stationary",
    expected_block_length=20,
    resamples=100_000,
    seed=42,
    null_policy="drop",
)
```

Defaults must be defensible across the stated input contract. If no broadly safe default exists, require the argument.

## Configuration

Global defaults are immutable values scoped with a context manager:

```python
with lc.config(threads=8, seed=42):
    result = run_study()
```

Precedence is:

1. explicit method argument;
2. active scoped configuration;
3. documented environment variable;
4. library default.

The resolved value, not merely the user-supplied override, enters provenance when it affects output.

## Typing

Lacuna ships `py.typed` and strictly types public interfaces.

Input types should recognize supported ecosystems without requiring them all at runtime. Prefer small protocols and guarded imports to large unions that import optional libraries. Result types are concrete and discoverable.

Do not use `Any` to avoid designing a public contract. `Any` is acceptable at an untyped third-party edge only when immediately normalized and never leaks into domain APIs.

Native stubs live beside the extension and match its exact callable surface. The public wrapper can expose a narrower or safer type than the raw binding.

## Errors and warnings

Use Lacuna's exception hierarchy:

- `DataContractError` for invalid schema, semantics, or unsupported input;
- `ConfigurationError` for invalid execution or method configuration;
- `NativeExtensionError` when a requested capability requires an unavailable native module;
- method-specific subclasses only when callers can act on them differently.

Errors state what was expected, what was observed, and how to correct it. Avoid broad exception swallowing around numerical or adapter calls.

Warnings are structured findings when they belong to research evidence. Python warnings are reserved for API deprecation, runtime environment concerns, or behavior that cannot be represented in a returned result.

## Missing values and small samples

Each function documents `null_policy`, `nan_policy`, and `inf_policy`. It also defines behavior for:

- an empty input;
- a group below minimum size;
- a constant signal or label;
- all ties;
- zero variance;
- undefined annualization frequency;
- absent optional evidence.

Undefined research evidence generally becomes a metric status or finding, not a fabricated zero.

## Result types

Domain results are immutable and JSON-serializable. They include:

- primary metrics;
- detailed source tables;
- findings and warnings;
- sample counts;
- method parameters and version;
- input fingerprint and seed when applicable.

Presentation helpers such as `to_markdown` may delegate to renderer modules, but computation never lives in a renderer.

## API review checklist

Before adding or changing a public call, answer:

1. What semantic input contract does it accept?
2. Which assumptions must be explicit?
3. What is the null/NaN/inf policy?
4. How are time and interval semantics represented?
5. What result type and units are returned?
6. What enters provenance and the method version?
7. Can the function preserve lazy input?
8. Does a study method delegate to this function?
9. Which errors are actionable to callers?
10. Is the target API clearly distinguished from implemented behavior in docs?
