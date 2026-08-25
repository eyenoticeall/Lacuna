# Implementation playbook

Use this playbook to convert a task into a narrow, evidence-backed change. The sequence is intentionally contract-first because late discovery of temporal or statistical ambiguity is expensive.

## 1. Establish the change boundary

Write a short working note with:

- requested user outcome;
- affected public/internal boundaries;
- status in the roadmap: implemented, v0.1 contract, or later;
- relevant method/schema/rule versions;
- files with existing user changes that must be preserved;
- checks available in the local environment.

Inspect package exports and tests before inventing new modules. Search for a concept by its domain name, result field, and configuration name because pre-alpha code may not yet match the target package map.

## 2. Specify behavior before code

For the affected operation, define:

- accepted containers, semantic fields, and dtypes;
- time, identity, sort, duplicate, null, NaN, and infinity rules;
- mathematical method, assumptions, and sample eligibility;
- outputs, warnings, findings, and provenance;
- deterministic behavior and RNG identity;
- errors versus valid-but-weak outcomes;
- memory/materialization and optional-dependency behavior.

If a choice changes the meaning of a result, it is public methodology, not an internal implementation detail.

## 3. Build a correctness oracle

Choose at least one:

- a direct, legible reference implementation;
- a hand-computed fixture;
- a published equation with independently generated inputs;
- a trusted external implementation used only for differential validation;
- a simulation with a known data-generating process.

Do not optimize the oracle. Its job is to make assumptions visible and failures diagnosable.

## 4. Create adversarial fixtures

Add the failure before the implementation when fixing a bug. For new work, include the hazards relevant to the domain:

- a record available one unit after decision time;
- overlapping label and test intervals;
- duplicate identifiers and revision ties;
- delisted entities;
- all-null, constant, singleton, and empty groups;
- NaN and infinity distinct from null;
- unsorted and chunked input;
- extreme weights or zero effective sample size;
- identical RNG work under different worker schedules;
- hostile report strings and artifact paths.

Fixtures should make an incorrect implementation obviously fail instead of relying on realistic data that may not activate the edge case.

## 5. Implement by ownership layer

Work from the outside contract inward:

1. public configuration and validation;
2. semantic data normalization;
3. reference analytical service;
4. structured result/provenance construction;
5. audit/report integration if requested;
6. optimized/native/backend dispatch only when justified.

This order keeps the Python API stable while implementations evolve. Do not move policy into Rust or presentation into analytical services for convenience.

## 6. Validate equivalence

Compare production behavior with the oracle across:

- ordinary cases;
- boundary and adversarial cases;
- randomized property cases;
- supported containers/backends;
- partitions, chunk layouts, and thread schedules;
- supported platforms when packaging behavior is affected.

Define tolerances from numerical behavior, not from whatever makes a test pass. Investigate systematic discrepancies even when aggregate error is small.

## 7. Measure before optimizing

Profile with end-to-end inputs. If a kernel warrants Rust or query pushdown, record:

- baseline and candidate implementations;
- data shape, dtype, grouping, null, and chunk characteristics;
- conversion, allocation, and materialization costs;
- latency distribution, peak memory, and thread count;
- numerical differences and tolerance.

Keep a safe fallback. Dispatch must be observable in provenance and must not alter methodology.

## 8. Update evidence and compatibility

Check whether the change needs a new:

- method version for changed calculation/assumptions;
- result schema version for changed fields/meaning;
- rule version for changed audit logic/threshold;
- score version for changed aggregation;
- bundle version for changed artifact layout;
- changelog entry for user-visible behavior.

Do not use the package version as a substitute for these independent identities.

## 9. Verify proportionally

Run focused tests during iteration, then all applicable checks in the root `AGENTS.md`. Documentation-only work still needs the strict docs build. A native or packaging change needs both language test suites and wheel smoke testing.

Read failures before editing. Do not broadly update golden files, relax tolerances, or add ignores until the semantic cause is understood.

## 10. Handoff

Report:

- what now works and how behavior is defined;
- files and public contracts changed;
- exact checks run and results;
- performance evidence if claimed;
- known limitations and deferred roadmap items;
- migrations or compatibility impact.

### Specialized branches

#### Native optimization

Begin with a profile and reference behavior. Add the core Rust kernel without Python policy, then PyO3 conversion/error mapping, differential tests, concurrency/GIL validation, and transfer-inclusive benchmarks.

#### Adapter integration

Begin with capability metadata and semantic column mapping. Add structural validation, explicit copy/materialization behavior, safe timestamp/identity rules, eager/lazy fixtures, and provenance. Analytical behavior belongs elsewhere.

#### Audit rule

Define required evidence and applicability before the threshold. Add pass/warn/fail/unknown/not-applicable fixtures, stable evidence references, rule versioning, score-coverage impact, and renderer escaping cases.

#### Schema or persistence change

Define compatibility and migration first. Test old reads, new writes, interrupted/concurrent operations, canonical serialization, invalid payload rejection, and explicit version negotiation.

#### Selection-aware or bootstrap inference

Begin with the null, estimand, direction convention, and complete candidate-family boundary. Keep
model-fitting splitters distinct from post-hoc performance-matrix procedures. Define ties,
partitions, block length, studentization, recentering, Monte Carlo correction, and degenerate
variance behavior before code. Resample synchronous strategy columns with one shared index path.
Validate against a literal equation-level implementation and at least one null-size and planted-power
simulation. For multiple null distributions, expose each rather than selecting the convenient one.
Use [Advanced inference](../methodology/advanced-inference.md) as the v0.5 reference contract.
