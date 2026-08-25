# Lacuna

**Stress-test your alpha before the market does.**

Lacuna is an open-source quantitative research validation library for discovering where an apparently promising signal, strategy, or research process is fragile. It is designed to sit between research/backtesting systems and a decision to trust their evidence.

!!! warning "Pre-1.0 status"

    The repository implements the v0.1 signal-validation path and the v0.2 robustness/experiment
    milestone: append-only trial lineage, multiplicity correction, parameter/temporal/universe
    perturbation, and regime evidence. It remains pre-1.0: later minor APIs may change through
    documented migrations, and target subsystem contracts do not imply release.

## Choose a path

| If you want to… | Start here |
| --- | --- |
| build and inspect the current package | [Getting started](getting-started/index.md) |
| understand ownership and data flow | [Architecture](concepts/architecture.md) |
| implement or review a change | [Engineering handbook](development/index.md) |
| understand time and table semantics | [Semantic data model](concepts/data-model.md) |
| add a statistical method | [Contributing a method](development/contributing-a-method.md) |
| implement a particular product area | [Subsystem contracts](subsystems/signal-labels.md) |
| direct a coding agent | [Agent handbook](agents/index.md) |
| look up project terminology | [Glossary](reference/glossary.md) |

## What Lacuna will validate

- signal information, quantile behavior, decay, turnover, and neutralization;
- time-aware validation, purging, embargo, bootstrap, and selection-aware inference;
- parameter, temporal, universe, and regime robustness;
- cost sensitivity, capacity, and implementation realism;
- look-ahead, revision, survivorship, and point-in-time data safety;
- experiment lineage, reproducibility, audit findings, and deterministic reports.

Lacuna is not a broker, data vendor, strategy generator, or full event-driven backtester. It consumes explicit research artifacts and returns structured evidence before it renders reports.

## Documentation model

The handbook is split by purpose:

- **Concepts** define stable architecture, time/data semantics, and evidence contracts.
- **Engineering** explains how to implement, test, optimize, package, and release.
- **Subsystems** specify domain ownership, algorithms, invariants, failure modes, and required tests.
- **Agent handbook** provides a repository operating contract and review playbooks.
- **Reference** records terminology and accepted architecture decisions.

The complete product proposal remains in `LACUNA_TECHNICAL_SPEC.md` at the repository root. These pages refine it into implementation contracts and clearly distinguish current behavior from target behavior.
