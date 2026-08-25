# Forward-return labels

`lacuna.labels.forward_returns` constructs the dependent variable used by signal diagnostics. Its
method version is `1`. The method answers: given the declared observation, entry, exit, and price
semantics, what simple return was earned over each requested horizon?

## Estimand

For instrument (i), observation (t), and horizon (h):

```text
r(i,t,h) = P_exit(i,t,h) / P_entry(i,t) - 1
```

The method produces simple, unannualized returns. It does not convert currencies, subtract a risk-free
rate, compound across rows, or infer a total-return series from a raw close.

## Input contract

The price table needs unique `(time, instrument)` rows and numeric entry/exit price columns. Eager and
lazy Polars, optional pandas/Arrow, and two-dimensional NumPy with an explicit `schema` are accepted at
the boundary. The method materializes, sorts by `(instrument, time)`, and records the source type, shape,
adapter copy classification, materialization reason, and subsequent execution operations.

`time` must be a Date, Datetime, Duration, integer observation index, or a whole-valued floating index
from a homogeneous NumPy matrix. `instrument` must be a non-null string, categorical, integer, or
whole-valued numeric identifier. Fractional identifiers, null semantic keys, and unsupported time
dtypes fail before sorting. The optional delisting-return column must be numeric.

Prices must be finite and strictly positive when present. Duplicate bars and infinite values are errors.
`missing="drop"` censors individual labels that lack a usable entry or exit; `missing="raise"` rejects
missing source prices or any horizon censoring. Other policy values are rejected rather than treated
as an implicit drop policy.

## Horizon clock

An integer or string such as `5` or `"5D"` means five ordered observations within each instrument.
It does not mean five calendar days. Integers normalize to `nD`; normalized duplicates are rejected.
Calendar, exchange-session, and custom offset horizons are outside v0.1.

For observation position (j):

| Entry | Entry position | Exit position for horizon (h) |
| --- | ---: | ---: |
| omitted / `current_close` | (j) | (j+h) |
| `next_close` | (j+1) | (j+h) |
| `next_open` | open at (j+1) | close at (j+h) |

A close-observed signal (`signal_time="close"`) cannot enter at the current close unless
`allow_same_close=True` explicitly accepts that availability assumption. A horizon cannot end before
the configured entry position.

## Label interval

Each output row contains:

```text
observation_time  label_start  entry_time  label_end
instrument        horizon      forward_return
```

`label_start` is the signal observation, while `entry_time` is the actual price-entry observation.
The sample interval is half-open `[label_start, label_end)`. Starting at the signal observation is
conservative for leakage purging and keeps a next-open one-observation label from collapsing to an
empty interval when the input only has one timestamp per session.

Rows are sorted by `(horizon, observation_time, instrument)`. The returned `LabelResult.frame` is a
clone of result-owned columnar data; compact construction evidence is available through
`LabelResult.evidence`.

## Corporate actions and delistings

`price_adjustment` is one of `raw`, `split_adjusted`, `total_return_adjusted`, or `unknown`. Lacuna
records the declaration; it does not transform the series. `unknown` emits
`PRICE_ADJUSTMENT_UNKNOWN`.

If `delisting_return` names a column, its value at the horizon endpoint substitutes when the ordinary
exit price is missing. Without that column, the result emits `DELISTING_RETURNS_UNKNOWN`. Supplying a
column declares a mechanism; the caller remains responsible for its economic definition and coverage.

## Example

```python
labels = lc.labels.forward_returns(
    prices,
    horizons=("1D", "5D", "20D"),
    time="date",
    instrument="instrument_id",
    price="close",
    signal_time="close",
    entry="next_open",
    price_adjustment="total_return_adjusted",
    delisting_return="delisting_return",
)
```

Inspect `coverage_by_horizon`, `source_missing_rows`, and `censored_rows` before interpreting downstream
statistics. A correctly computed return can still be a biased label if the source universe or price
history is not point-in-time safe.

## Validation evidence

The implementation is covered by hand-computed current/next-entry fixtures, missing/delisting and
same-close errors, scale invariance, NumPy/pandas/Arrow/Polars equivalence, lazy/eager equivalence, and
explicit interval tests.
