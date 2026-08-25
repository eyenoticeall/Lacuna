# Lacuna audit

## Summary

- Robustness score: **80 / 100**
- Evidence coverage: **0.8**
- Failures: **0**
- Warnings: **0**
- Unknown checks: **1**
- Not applicable: **0**

## Findings

### PASS · Information coefficient is defined

- Code: `IC_DEFINED`
- Severity: `high`
- Category: `statistical_validity`

The IC time series contains a defined aggregate correlation.

Evidence: `mean_ic`=0.04, `rule_version`=1, `weight`=12

### UNKNOWN · Research trial history is available

- Code: `TRIAL_HISTORY_AVAILABLE`
- Severity: `high`
- Category: `experiment_integrity`

experiment trial history was not supplied

Evidence: `rule_version`=1, `weight`=2

## Evidence tables

### Finding Summary

| count | state |
| --- | --- |
| 1 | PASS |
| 1 | UNKNOWN |

### Score Components

| category | earned_weight | possible_weight | score | unknown_weight |
| --- | --- | --- | --- | --- |
| statistical_validity | 80 | 100 | 80 | 20 |

## Methodology and provenance

- Method: `audit.v0_1`
- Method version: `1`
- Schema version: `1`
- Created at: `2026-08-26 12:00:00+00:00`
- Parameters: `{"not_applicable_policy":"excluded","score_version":1,"unknown_credit":0.0,"warn_credit":0.5}`

### Method warnings

- Representative compatibility fixture; values are illustrative.
