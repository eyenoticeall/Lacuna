"""Optional DuckDB-to-Arrow interoperability without pandas materialization."""

from __future__ import annotations

from collections.abc import Sequence
from numbers import Integral

import polars as pl

from lacuna.adapters.polars import frame_summary, require_columns, to_polars
from lacuna.adapters.types import AdaptedFrame
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import AnalysisResult, ResultMetadata


def _reader(source: object, batch_size: int) -> tuple[object, str]:
    preferred = getattr(source, "to_arrow_reader", None)
    if callable(preferred):
        try:
            return preferred(batch_size), "to_arrow_reader"
        except Exception as error:
            raise DataContractError(
                "DuckDB failed to produce an Arrow record-batch reader"
            ) from error

    # DuckDB versions before to_arrow_reader exposed fetch_record_batch. Keep
    # the compatibility path explicit in provenance rather than hiding it.
    legacy = getattr(source, "fetch_record_batch", None)
    if callable(legacy):
        try:
            return legacy(batch_size), "fetch_record_batch_legacy"
        except Exception as error:
            raise DataContractError(
                "DuckDB failed to produce an Arrow record-batch reader"
            ) from error

    raise DataContractError(
        "DuckDB input must be an executed connection or relation exposing to_arrow_reader(); "
        "install the 'duckdb' extra and pass a trusted in-process DuckDB result"
    )


def from_duckdb(
    source: object,
    *,
    batch_size: int = 100_000,
    required: Sequence[str] = (),
    collect: bool = True,
) -> AdaptedFrame:
    """Normalize a trusted DuckDB result through its Arrow record-batch reader.

    The adapter never accepts or generates SQL. Callers retain responsibility
    for query construction and parameter binding. The preferred DuckDB API is
    ``to_arrow_reader``; the legacy ``fetch_record_batch`` path is recorded
    when required for compatibility.
    """

    if isinstance(batch_size, bool) or not isinstance(batch_size, Integral) or batch_size < 1:
        raise MethodContractError("batch_size must be a positive integer")
    if not isinstance(collect, bool):
        raise MethodContractError("collect must be boolean")
    if any(not isinstance(column, str) or not column for column in required):
        raise MethodContractError("required must contain non-empty column names")
    if len(set(required)) != len(required):
        raise MethodContractError("required column names must be unique")

    reader, reader_method = _reader(source, int(batch_size))
    try:
        frame = to_polars(reader, collect=collect)
    except DataContractError:
        raise
    except Exception as error:  # pragma: no cover - defensive producer boundary
        raise DataContractError("DuckDB Arrow result could not be normalized") from error
    require_columns(frame, required)
    summary = frame_summary(frame)
    row_count = frame.height if isinstance(frame, pl.DataFrame) else None
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="adapters.duckdb_arrow",
            method_version=1,
            parameters={
                "source_type": f"{type(source).__module__}.{type(source).__name__}",
                "reader_method": reader_method,
                "batch_size": int(batch_size),
                "required_columns": tuple(required),
                "materialized": isinstance(frame, pl.DataFrame),
                "copy_classification": "arrow_stream_to_polars",
                "sql_generated": False,
            },
        ),
        metrics={
            "column_count": len(summary.columns),
            "row_count": row_count,
        },
        tables={"columns": tuple({"column": column} for column in summary.columns)},
    )
    return AdaptedFrame(frame=frame, evidence=evidence)


__all__ = ["from_duckdb"]
