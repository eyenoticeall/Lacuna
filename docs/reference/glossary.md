# Glossary

Terms in this glossary are normative where they describe Lacuna data and evidence contracts. Mathematical conventions can vary across finance libraries, so public APIs must name any intentional departure.

## Time and data

**Available time**
: Earliest timestamp at which a record could have been known to the strategy or researcher. This is the primary right-side timestamp for point-in-time joins.

**Decision time**
: Timestamp at which a signal or portfolio decision is formed. Inputs used by that decision must already be available.

**Effective time**
: Timestamp from which a fact applies economically or legally. It may precede publication and therefore does not prove availability.

**Event time**
: Timestamp when the underlying real-world event occurred.

**Observation time**
: Timestamp assigned to the recorded measurement, such as a market bar close.

**Execution time**
: Timestamp at which a hypothetical or real trade is assumed to execute.

**Revision time**
: Timestamp at which a corrected or restated version became available.

**Label interval**
: Half-open interval `[label_start, label_end)` whose observations determine a supervised target or forward outcome.

**Half-open interval**
: An interval containing its start and excluding its end: `[start, end)`. It makes adjacent periods unambiguous.

**Point-in-time safe**
: A transformation that uses only records and versions available by each decision time, under the declared source and timing policy.

**Information age**
: `decision_time - available_time` for a matched record. It is useful for stale-data diagnostics.

**Stable instrument ID**
: Durable entity identity independent of ticker reuse, venue changes, or display-symbol changes.

**Universe membership**
: Time-bounded evidence that an instrument belongs to an eligible research universe. Historical membership must include removals and delistings when claiming survivorship safety.

**Semantic column**
: A role such as `signal`, `price`, `decision_time`, or `instrument_id`, independent of the physical source column name.

**Materialization**
: Converting a lazy, streaming, or external representation into in-memory concrete data.

**Zero-copy**
: Reusing compatible memory buffers across a boundary without copying their contents. It does not mean zero validation or zero metadata allocation.

## Signal and portfolio research

**Signal**
: A time- and entity-indexed numerical research input used to rank, forecast, or allocate.

**Label**
: A future outcome aligned to a signal observation under explicit timing and price conventions.

**Forward return**
: Return from a declared entry price/time to a future exit price/time. Horizon alone is insufficient to define it.

**Information coefficient (IC)**
: Cross-sectional association between a signal and subsequent label, commonly Pearson or Spearman correlation at each evaluation date.

**Information coefficient information ratio (ICIR)**
: Mean IC divided by its variability, with an explicitly declared annualization and dependence treatment.

**Quantile portfolio**
: Groups formed by signal rank or value boundaries for comparing subsequent outcomes.

**Monotonicity**
: Degree to which quantile outcomes progress consistently with signal rank.

**Turnover**
: Change in holdings, ranks, or weights between rebalance points under a declared definition.

**Decay**
: Change in signal efficacy as the label or execution horizon moves away from the signal time.

**Neutralization**
: Removal of specified exposures from a signal or outcome, with the fit window and available covariates explicitly controlled.

## Validation and inference

**Walk-forward validation**
: Chronological train/test evaluation in which each test period follows its training period.

**Purging**
: Removing training observations whose label intervals overlap a test interval.

**Embargo**
: Excluding observations near a test boundary to reduce information leakage or dependence.

**Combinatorial purged cross-validation (CPCV)**
: A later-stage validation design that evaluates combinations of test groups with purging and uses the resulting paths to assess selection risk.

**Bootstrap**
: Resampling procedure used to approximate a statistic's sampling distribution.

**Block bootstrap**
: Bootstrap that resamples contiguous observations or blocks to preserve local dependence.

**Stationary bootstrap**
: Block bootstrap with geometrically distributed block lengths, conventionally parameterized so expected block length is `1 / p`.

**Permutation test**
: Test that compares an observed statistic with values under a declared exchangeability-preserving permutation scheme.

**Probabilistic Sharpe ratio (PSR)**
: Probability-like inference for whether an observed Sharpe ratio exceeds a benchmark under stated distributional and sample assumptions.

**Deflated Sharpe ratio (DSR)**
: Sharpe inference adjusted for selection across multiple tried strategies and non-normal return characteristics.

**Probability of backtest overfitting (PBO)**
: Estimate of how often selection in one sample leads to poor relative performance out of sample under a combinatorial validation design.

**Effective sample size**
: Information-equivalent sample size after weights or dependence reduce the contribution of nominal observations.

**Family-wise error rate (FWER)**
: Probability of at least one false rejection within a declared hypothesis family.

**False discovery rate (FDR)**
: Expected proportion of false rejections among rejected hypotheses.

## Robustness and trading realism

**Parameter surface**
: Metric values evaluated over a declared grid or neighborhood of parameter settings.

**Stability neighborhood**
: Predeclared parameter values considered close enough to assess whether performance is isolated or persistent.

**Regime**
: Market-state classification calculated only from information available at the relevant time.

**Cost model**
: Mapping from trades and market state to estimated execution, fee, financing, or borrow costs.

**Break-even cost**
: Uniform cost assumption at which the evaluated strategy metric reaches a declared zero or acceptance boundary.

**Capacity**
: Estimated deployable capital or participation level before costs or constraints violate an objective.

**Participation rate**
: Traded quantity divided by a declared contemporaneous market-volume measure.

## Evidence and reproducibility

**AnalysisResult**
: Lacuna's structured analytical boundary containing metrics, typed tables, findings, provenance, warnings, and versions.

**Finding state**
: Evidence conclusion: `PASS`, `WARN`, `FAIL`, `UNKNOWN`, or `NOT_APPLICABLE`.

**Severity**
: Potential consequence of a finding, independent of its current state.

**Unknown**
: Required evidence is missing or insufficient to determine the rule outcome. It is never an implicit pass.

**Not applicable**
: The rule does not apply to the declared methodology or scope.

**Provenance**
: Structured record of data identities, semantic mappings, resolved configuration, method/backend versions, randomness, and environment needed to interpret or reproduce evidence.

**Method version**
: Identity of a calculation and its assumptions. It changes when statistical meaning changes even if the result schema does not.

**Schema version**
: Identity of a serialized structure and field semantics.

**Rule version**
: Identity of audit applicability, threshold, and evaluation behavior.

**Score version**
: Identity of weights, state treatment, normalization, and aggregation used for an audit score.

**Experiment family**
: Declared set of comparable trials associated with one research question and search process.

**Trial**
: One fully specified experiment parameterization and semantic input identity.

**Attempt**
: One execution of a trial, including failure, cancellation, or retry.

**Selection lineage**
: Record of candidate trials, criterion, constraints, tie behavior, and decision used to choose an experiment.

**Fingerprint**
: Versioned digest of a canonical identity descriptor. It detects changed modeled inputs but cannot prove equivalence of unrecorded state.

**Numerical reproducibility**
: Ability to recompute outputs within declared method-specific tolerances.

**Bitwise reproducibility**
: Ability to reproduce identical artifact bytes, a stricter property that is not guaranteed for every platform or backend.

## Runtime and extension terms

**Reference implementation**
: Intentionally clear implementation or fixture used as a correctness oracle for optimized paths.

**Native kernel**
: Coarse-grained Rust computation exposed through the Python extension after its contract is validated.

**Execution planner**
: Component that selects a backend, materialization strategy, and resource plan without changing methodology.

**Adapter**
: Translation layer that maps an external container or system into Lacuna contracts without silently adding research policy.

**Plugin**
: Explicitly activated trusted Python extension contributing a versioned Lacuna capability.
