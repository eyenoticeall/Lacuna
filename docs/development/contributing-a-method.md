# Contributing an analytical method

This is the implementation template for a new statistic, splitter, diagnostic, or audit rule.

## 1. Define the research question

Start with one sentence that the output can answer. Examples:

- “Does this cross-sectional signal rank future returns within each date?”
- “Do training labels overlap the test interval?”
- “How sensitive is net performance to plausible spread and slippage?”

If the question is ambiguous, the API and findings will be ambiguous too.

## 2. Write the method contract

Document before implementation:

- semantic inputs and required columns;
- time and interval meanings;
- formula or algorithm;
- assumptions;
- null, NaN, infinity, tie, and duplicate policy;
- minimum samples and undefined cases;
- output metrics, tables, units, and findings;
- randomization and seed behavior;
- expected execution path;
- known failure modes and when not to use the method.

Place subsystem constraints in the relevant architecture guide and user-facing mathematics in a methodology page.

## 3. Assign a method version

Start at version 1. The version changes when formulas, sample selection, tie behavior, interval closure, default inference, or another value-affecting semantic changes.

Pure performance changes that preserve outputs and policies do not increment the method version.

## 4. Implement a reference path

The reference implementation favors clarity and independent logic. It may be slower, but it must avoid per-row Python loops on large production paths. For small testing-only implementations, explicit loops can be useful when they make the definition obvious.

Keep the reference callable in tests. It is not throwaway scaffolding.

## 5. Build result contracts

Define immutable typed outputs before presentation. Include:

- primary metrics;
- counts and effective sample sizes;
- detailed source tables;
- assumptions and parameters;
- warnings/findings;
- method and schema versions;
- seed and input fingerprint.

Undefined values carry a reason or status. Do not substitute zero.

## 6. Add correctness evidence

At minimum:

- hand-computed unit fixture;
- independent reference comparison;
- edge-case matrix;
- property/invariant tests;
- serialization test;
- adapter equivalence where relevant;
- temporal boundary tests for label-aware methods.

Randomized or inferential methods add simulation-calibration tests.

## 7. Choose execution ownership

Profile a realistic public call. Use Polars for columnar plans, NumPy/SciPy for mature math, and Rust only after profiling and a representative benchmark.

If adding native code:

- keep the Python contract authoritative;
- make one coarse call;
- release the interpreter lock;
- differentially test all policies;
- benchmark runtime and memory;
- preserve deterministic results across threads.

## 8. Integrate audit evidence

Domain computation should not hard-code global audit conclusions. It may emit method-specific warnings. Audit rules consume domain results and map explicit thresholds to findings.

Missing inputs become `UNKNOWN` when the check is relevant. Unsupported conditions should not disappear silently.

## 9. Document the method

Add:

- API reference with types and defaults;
- methodology formula and assumptions;
- worked example;
- interpretation guide;
- failure modes and misuse warnings;
- performance/materialization behavior;
- references and validation sources.

Target APIs in examples are marked clearly until shipped.

## 10. Complete the review record

A change description should state:

```text
Research question:
Method/version:
Temporal semantics:
Missing-data policy:
Reference evidence:
Property/simulation evidence:
Execution/backend decision:
Benchmark and memory result:
Result schema impact:
Documentation added:
Known limitations:
```

## Method completion checklist

- [ ] The research question is precise.
- [ ] Inputs and time meanings are explicit.
- [ ] Formula and assumptions are documented.
- [ ] Edge and undefined cases are specified.
- [ ] Reference implementation exists.
- [ ] Typed immutable result exists.
- [ ] Unit/reference/property tests pass.
- [ ] Simulation tests exist where relevant.
- [ ] Native and reference paths agree, if applicable.
- [ ] Benchmarks justify execution routing.
- [ ] Provenance records effective choices.
- [ ] Methodology and API documentation are complete.
- [ ] Changelog and schema/method versions are updated.
