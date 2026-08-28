# Dataframe and Arrow boundary

Adapters let Lacuna participate in existing research stacks without adopting a proprietary dataframe.

## Boundary responsibilities

An adapter may:

- recognize a supported edge object;
- preserve or expose Arrow-compatible buffers;
- normalize a physical representation into Polars or primitive arrays;
- report whether the path stayed lazy or materialized;
- validate physical schema and required columns;
- translate edge-specific errors into `DataContractError`.

An adapter may not:

- choose research defaults;
- construct labels;
- compute domain statistics;
- silently sort or aggregate unless the adapter contract explicitly says so;
- drop nulls, NaNs, duplicate rows, timezones, or categorical identity;
- import an optional ecosystem unconditionally.

## Preferred paths

| Input | Preferred handling |
|---|---|
| `polars.LazyFrame` | inspect schema lazily; keep lazy until an algorithm requires collection |
| `polars.DataFrame` | preserve columns/chunks where compatible |
| `polars.Series` | convert to a named single-column frame |
| Arrow table/batch/reader | use Arrow C interfaces or `polars.from_arrow` |
| pandas dataframe/series | optional adapter through Arrow-compatible conversion |
| NumPy 1D | named value column |
| NumPy 2D | require explicit column schema |
| DuckDB result | implemented Arrow record-batch stream, no pandas intermediate |

The implemented `to_polars` helper is a physical normalization foundation, not a domain validator.

## Copy classification

Every adapter path should eventually report one of:

- **zero-copy** — buffers are shared and no normalization allocation occurred;
- **potentially zero-copy** — depends on chunks, dtype, or producer behavior;
- **one-copy** — one documented normalization allocation;
- **materializing** — lazy/streaming input was collected or reorganized.

Claims are path-specific. “Arrow compatible” does not guarantee zero-copy.

The implemented v0.1 evidence records adapter behavior under each result's input parameters:

- `adapter_copy` classifies the boundary as `zero_copy`, `potentially_zero_copy`, `one_copy`, or
  `materializing`;
- `adapter_operations` names the physical conversion path;
- `lazy_input`, `materialized`, and `materialization_reason` distinguish a lazy source from an
  actual collection boundary;
- `execution_operations` lists projections, casts, joins, sorts, or derived-column work performed
  after normalization.

These are conservative path classifications, not byte counters. In particular, a
`potentially_zero_copy` Arrow or NumPy path depends on producer layout, chunking, dtype, and Polars.
`materializing` means a lazy source was deliberately collected because the current domain algorithm
requires eager data.

Common copy causes include:

- dtype coercion;
- incompatible null layout;
- rechunking;
- sorting;
- categorical/dictionary normalization;
- contiguity or alignment requirements;
- mutable scratch space;
- timezone or unit conversion.

## Lazy execution

Functions declare whether they are:

- lazy-preserving;
- streaming-compatible;
- bounded materialization;
- fully materializing.

Schema validation uses `collect_schema()` or equivalent metadata, not `collect()`. A function that requires global materialization estimates or reports size when practical and never hides the operation behind an innocuous adapter call.

## Column resolution

Domain APIs accept semantic column parameters, for example:

```python
lc.signal.ic(
    signal_data,
    label_data,
    signal_time="date",
    label_time="date",
    instrument="asset_id",
    signal_value="momentum",
    label_value="fwd_5d",
)
```

Column resolution happens once in Python. Internal normalized names may be used in a projection, but result metadata preserves the user mapping.

## Dtypes

Default expectations:

- analytics: `float64`;
- flags: boolean;
- group IDs: integer or dictionary/categorical;
- timestamps: timezone-aware where source semantics require it;
- horizons: normalized duration/category representation;
- instrument IDs: stable integer, string, or dictionary values.

Coercion is explicit. Narrowing numeric types requires a precision policy. Timestamp unit changes and timezone stripping are never incidental.

## Chunking and ordering

Arrow and Polars inputs may contain multiple chunks. A kernel either supports chunk iteration or explicitly rechunks and records the allocation.

Sorting belongs to the domain execution plan. Adapters preserve order unless their documented contract says otherwise. Domain functions declare required keys and whether stable tie ordering affects output.

## pandas behavior

pandas is an edge format. The optional adapter documents:

- index inclusion or exclusion;
- timezone conversion;
- categorical mapping;
- nullable extension dtype behavior;
- whether PyArrow is required;
- copy behavior for each common dtype family.

Never treat a pandas index as `time` or `instrument` without an explicit argument or named adapter contract.
The factor-panel adapter is that named contract: it includes a named pandas index level only when
`FactorPanelSchema.columns` explicitly maps the corresponding source name. Index names and
frequency metadata never supply timing semantics; those live in `FactorPanelSemantics`.

## DuckDB behavior

`from_duckdb` accepts an already executed trusted relation/connection exposing an Arrow reader. It
prefers `to_arrow_reader(batch_size)` and records use of the legacy `fetch_record_batch` path. The
adapter performs no SQL parsing or interpolation, preserves Arrow null/timezone metadata through
Polars normalization, and can return an eager or lazy normalized frame according to `collect`.

This is a conversion boundary, not query pushdown. A caller constructing SQL must use DuckDB's
parameter binding and validate any dynamic identifiers; Lacuna never treats a string as a query.

## Arrow safety

Only accept in-process Arrow C pointers from trusted producers. External Arrow IPC, Parquet, or other files go through validated readers rather than arbitrary capsules.

Validate:

- field names and types;
- buffer and child counts;
- offsets and lengths;
- null bitmap length;
- dictionary indices;
- lifecycle and release ownership.

## Adapter tests

Each input family needs tests for:

- eager and lazy behavior;
- series and frame inputs;
- empty and chunked input;
- null and NaN preservation;
- timestamps and timezones;
- categorical IDs;
- copy/materialization classification;
- missing optional dependency errors;
- unsupported object errors;
- equivalence of normalized output across adapters.
