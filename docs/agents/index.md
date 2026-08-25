# Agent handbook

This handbook tells coding agents how to turn Lacuna's technical design into reviewable changes. The repository-root `AGENTS.md` is the binding repository-wide contract; these pages expand its workflows and review questions.

## Document hierarchy

1. User instructions define the requested outcome.
2. Repository policy and a directory-local `AGENTS.md`, if one exists, constrain the work.
3. The root `AGENTS.md` defines cross-repository invariants.
4. Concept and subsystem guides define the target contracts.
5. Current code and tests establish implemented behavior.

When these disagree, do not quietly choose one. Preserve working behavior unless the task authorizes a change, document the mismatch, and resolve high-impact ambiguity before expanding scope.

## Task router

| Task | First documents | Expected evidence |
| --- | --- | --- |
| implement a statistical method | method-contribution guide + subsystem guide; advanced-inference guide for selection/bootstrap work | reference, assumptions, fixtures, method version |
| optimize in Rust | native-core + performance guides | profile, differential tests, transfer-inclusive benchmark |
| add a data container/source | data-boundary + adapters guide | semantic mapping, copy plan, eager/lazy tests |
| add or activate a plugin | adapters/plugins guide + security rules | metadata-only discovery, explicit trust, protocol/evidence tests |
| change an extension package | extension subsystem + release guide | independent version/API fixture, isolated build and joint smoke test |
| fix a temporal bug | data model + bias/CV guide | boundary fixture, leakage analysis, affected outputs |
| add an audit rule | evidence model + audit guide | applicability cases, rule version, score effect |
| change report output | audit/report guide | schema compatibility, escaping, golden diff |
| change experiment storage | experiment guide | migration, concurrency, canonicalization tests |
| change public API | Python API + release guide | compatibility assessment, typing, docs/changelog |

## Core behavior

An effective agent makes the smallest coherent change that preserves Lacuna's epistemic guarantees. It does not equate successful execution with valid research. It asks whether the data was knowable, the method assumptions hold, the selected evidence is complete, and the result can be reproduced.

Read [The implementation playbook](implementation-playbook.md) before building and use [The review checklist](review-checklist.md) before handoff.
