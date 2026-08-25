# Data and time

Lacuna's data model is a set of semantic schemas over Arrow-compatible columnar data. It is not a custom dataframe implementation.

## Time is part of the contract

The word `time` is insufficient whenever multiple temporal meanings exist. Use explicit names:

| Field | Meaning |
|---|---|
| `event_time` | When the underlying economic event occurred |
| `observation_time` | Timestamp associated with a recorded observation |
| `available_time` | Earliest time the researcher could have known the value |
| `effective_time` | Time the value became economically applicable |
| `revision_time` | Time a historical value version was published |
| `decision_time` | Time a strategy made its decision |
| `execution_time` | Time the simulated or observed trade executed |
| `label_start` | Inclusive start of a target interval |
| `label_end` | Exclusive end of a target interval unless a method documents otherwise |

Every API must state its interval closure and timezone rules. Intraday timestamps keep timezone information. Converting between calendars or timezones is an explicit operation, never an incidental adapter side effect.

## Instrument identity

`instrument` or `instrument_id` is the stable analytical identity. A ticker is metadata because tickers can be reused or changed.

Recommended identity metadata:

```text
instrument_id
symbol
exchange
currency
valid_from
valid_to
```

String, integer, and Arrow dictionary identifiers are acceptable. An adapter may normalize physical representation, but it must not silently equate distinct identifiers.

## Semantic frames

### Observation frame

Minimum columns:

```text
time
instrument
value
```

Optional columns include `available_time`, `group`, `weight`, `universe`, `source`, and `revision_time`.

### Signal frame

```text
time: timestamp
instrument: stable identifier
signal: float64
[group...]
[weight]
[universe]
```

Rows represent observations, not orders or portfolio positions. A signal contract must document whether higher values imply larger expected returns.

### Price frame

```text
time
instrument
open
high
low
close
volume
```

Only columns required by the requested label or cost calculation are mandatory. Price-adjustment metadata must be one of `raw`, `split_adjusted`, `total_return_adjusted`, or `unknown`.

### Label frame

```text
observation_time
label_start
entry_time
label_end
instrument
label
```

`label_start` conservatively begins at the signal observation so purging covers the complete
sample-information interval. `entry_time` records the actual price-entry observation. The interval
is mandatory for label-aware cross-validation; a scalar label without its earning interval cannot
prove that a split is leakage-free.

### Forward-return frame

Long form is canonical at public boundaries:

```text
observation_time
label_start
entry_time
label_end
instrument
horizon
forward_return
```

Internal kernels may use wide or matrix layouts when conversion is measured and recorded.

### Trade frame

Minimum recommended columns:

```text
decision_time
execution_time
instrument
side
quantity
price
reference_price
```

Optional microstructure fields include bid, ask, mid, volume, ADV, volatility, commission, borrow rate, venue, order ID, and strategy ID.

### Experiment trial

```text
trial_id
created_at
family
parameters
sample_start
sample_end
universe
metric
metric_value
selected
input_hash
code_hash
```

Trial history is evidence for multiple-testing analysis, not incidental logging.

## Validation order

Public functions validate in this order:

1. Resolve column names and explicit configuration.
2. Inspect the schema without materializing a lazy input where possible.
3. Validate required columns and physical dtypes.
4. Validate semantic constraints such as interval ordering and uniqueness.
5. Apply the documented null, NaN, and infinity policy.
6. Normalize ordering or chunking only when required by the algorithm.
7. Record copies, materialization, sorting, and coercions in diagnostics or provenance.

Fail early with a `DataContractError` that names the field, expected contract, and observed condition.

## Null and numeric policy

Arrow null and IEEE NaN are different states. Every public method declares separate behavior for:

- null values;
- NaN values;
- positive and negative infinity;
- duplicate keys;
- insufficient groups;
- tied values;
- empty input.

Allowed policies are explicit values such as `raise`, `drop`, `propagate`, or a method-specific named policy. Silent coercion is not allowed.

Numerical analytics use `float64` by default. A lower-precision path requires a documented error budget and benchmark showing that the memory or throughput benefit is material.

## Ordering and uniqueness

Algorithms must declare required sort keys. Common panel ordering is `(time, instrument)`, but callers must not assume adapters sort unless the API promises it.

When one row per `(time, instrument)` is required, duplicates produce an error or an explicitly configured aggregation. “Keep first” is never a safe implicit policy.

## Lazy data

Schema inspection should preserve laziness. Operations that require global sorting, random access, or native contiguous buffers may materialize, but must do so deliberately. An API must not turn a very large `LazyFrame` into memory merely to validate column names.

## Required tests

Every new semantic frame validator needs tests for:

- minimum valid schema;
- optional fields;
- missing and wrongly typed required fields;
- duplicate logical keys;
- unsorted input when ordering matters;
- timezone-aware intraday values;
- null, NaN, and infinity policies;
- empty frames and one-row groups;
- lazy schema validation without collection.
