from __future__ import annotations

import math
from datetime import UTC, date, datetime

import polars as pl
import pytest
from lacuna import standard_audit
from lacuna.exceptions import DataContractError, MethodContractError

from lacuna_options import OptionChain, delta_buckets, empirical_residual, validate_chain


def _chain_records() -> dict[str, list[object]]:
    return {
        "time": [date(2026, 1, 1), date(2026, 1, 1)],
        "instrument": ["A-C", "A-P"],
        "underlying": ["A", "A"],
        "expiration": [date(2026, 7, 2), date(2026, 7, 2)],
        "strike": [100.0, 90.0],
        "option_type": ["call", "put"],
        "bid": [4.0, 2.0],
        "ask": [6.0, 4.0],
        "underlying_price": [95.0, 95.0],
        "rate": [0.05, 0.05],
        "dividend": [0.01, 0.01],
        "iv": [0.24, 0.30],
        "delta": [0.45, -0.20],
        "expected_iv": [0.20, 0.32],
    }


def test_validate_chain_derives_mid_forward_and_log_moneyness() -> None:
    result = validate_chain(pl.DataFrame(_chain_records()), year_basis=365.25)

    assert isinstance(result, OptionChain)
    assert result.frame.get_column("mid").to_list() == [5.0, 3.0]
    maturity = 182.0 / 365.25
    expected_forward = 95.0 * math.exp((0.05 - 0.01) * maturity)
    assert result.frame.get_column("time_to_expiry_years").to_list() == pytest.approx(
        [maturity, maturity]
    )
    assert result.frame.get_column("forward").to_list() == pytest.approx(
        [expected_forward, expected_forward]
    )
    assert result.frame.get_column("log_moneyness").to_list() == pytest.approx(
        [math.log(100.0 / expected_forward), math.log(90.0 / expected_forward)]
    )
    assert result.evidence.metadata.parameters["mid_computed"] is True


def test_validated_chain_enters_the_options_standardized_audit_profile() -> None:
    chain = validate_chain(_chain_records())

    report = standard_audit(results={"chain": chain.evidence}, scope="options")
    requirement_rows = report.table("evidence_requirements")
    assert isinstance(requirement_rows, list)
    options_row = next(row for row in requirement_rows if row["capability"] == "options_evidence")
    assert options_row["disposition"] == "required"
    assert options_row["present"] is True
    assert report.metrics["recognized_result_count"] == 1


def test_validate_chain_supports_explicit_mapping_and_timezone_preservation() -> None:
    source = pl.DataFrame(
        {
            "quote_time": [datetime(2026, 1, 1, tzinfo=UTC)],
            "contract": ["A-C"],
            "root": ["A"],
            "expiry": [datetime(2026, 2, 1, tzinfo=UTC)],
            "k": [100.0],
            "right": ["call"],
            "best_bid": [1.0],
            "best_ask": [2.0],
            "spot": [99.0],
            "risk_free": [0.03],
            "yield": [0.0],
        }
    ).lazy()
    mapping = {
        "time": "quote_time",
        "instrument": "contract",
        "underlying": "root",
        "expiration": "expiry",
        "strike": "k",
        "option_type": "right",
        "bid": "best_bid",
        "ask": "best_ask",
        "underlying_price": "spot",
        "rate": "risk_free",
        "dividend": "yield",
    }

    result = validate_chain(source, columns=mapping)

    assert result.frame.schema["time"].time_zone == "UTC"  # type: ignore[union-attr]
    assert result.frame.schema["expiration"].time_zone == "UTC"  # type: ignore[union-attr]
    assert result.evidence.metadata.parameters["materialized"] is True


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("expiration", date(2026, 1, 1), "strictly after"),
        ("strike", 0.0, "strikes and underlyings"),
        ("bid", -1.0, "quotes non-negative"),
        ("ask", 3.0, "bid <= ask"),
        ("option_type", "CALL", "explicit 'call' or 'put'"),
        ("iv", 0.0, "implied volatility must be positive"),
        ("delta", 1.1, "delta must lie"),
    ],
)
def test_validate_chain_rejects_invalid_market_contracts(
    column: str,
    value: object,
    message: str,
) -> None:
    records = _chain_records()
    records[column][0] = value
    if column == "ask":
        records["bid"][0] = 4.0
    with pytest.raises(DataContractError, match=message):
        validate_chain(records)


def test_validate_chain_rejects_bad_mid_and_mixed_temporal_dtypes() -> None:
    records = _chain_records()
    records["mid"] = [10.0, 3.0]
    with pytest.raises(DataContractError, match="inclusive bid/ask"):
        validate_chain(records)

    records = _chain_records()
    records["expiration"] = [
        datetime(2026, 7, 2, tzinfo=UTC),
        datetime(2026, 7, 2, tzinfo=UTC),
    ]
    with pytest.raises(DataContractError, match="same physical dtype"):
        validate_chain(records)


def test_validate_chain_rejects_mapping_schema_and_physical_defects() -> None:
    with pytest.raises(MethodContractError, match="canonical-to-source mapping"):
        validate_chain(_chain_records(), columns=[("time", "date")])  # type: ignore[arg-type]
    with pytest.raises(MethodContractError, match="non-empty string"):
        validate_chain(_chain_records(), columns={"time": ""})
    with pytest.raises(MethodContractError, match="unknown canonical"):
        validate_chain(_chain_records(), columns={"unknown": "source"})
    with pytest.raises(MethodContractError, match="map uniquely"):
        validate_chain(_chain_records(), columns={"time": "instrument"})

    records = _chain_records()
    records.pop("strike")
    with pytest.raises(DataContractError, match="missing required columns"):
        validate_chain(records)

    records = _chain_records()
    records["strike"] = ["100", "90"]
    with pytest.raises(DataContractError, match="invalid dtypes"):
        validate_chain(records)

    records = _chain_records()
    records["strike"][0] = None
    with pytest.raises(DataContractError, match="must not contain nulls"):
        validate_chain(records)

    records = _chain_records()
    records["time"] = [1, 1]
    records["expiration"] = [2, 2]
    with pytest.raises(DataContractError, match="Date or Datetime"):
        validate_chain(records)


def test_validate_chain_rejects_invalid_optional_nonnegative_fields_and_empty_input() -> None:
    records = _chain_records()
    records["gamma"] = [-0.1, 0.1]
    with pytest.raises(DataContractError, match="must be non-negative"):
        validate_chain(records)

    with pytest.raises(DataContractError, match="at least one quote"):
        validate_chain(pl.DataFrame(_chain_records()).clear())


def test_delta_buckets_use_absolute_delta_and_closed_final_boundary() -> None:
    records = _chain_records()
    records["delta"] = [0.0, -1.0]
    chain = validate_chain(records)

    result = delta_buckets(chain, edges=(0.0, 0.25, 0.5, 1.0))

    assert result.frame.get_column("delta_bucket").to_list() == ["[0.00,0.25)", "[0.50,1.00]"]
    assert result.evidence.metrics["occupied_buckets"] == 2
    with pytest.raises(MethodContractError, match="starting at 0 and ending at 1"):
        delta_buckets(chain, edges=(0.1, 1.0))
    with pytest.raises(MethodContractError, match="finite numeric boundaries"):
        delta_buckets(chain, edges=(0.0, "middle", 1.0))  # type: ignore[arg-type]


def test_delta_buckets_require_validated_delta_evidence() -> None:
    records = _chain_records()
    records.pop("delta")
    chain = validate_chain(records)
    with pytest.raises(DataContractError, match="requires a validated delta"):
        delta_buckets(chain)
    with pytest.raises(MethodContractError, match="result of validate_chain"):
        delta_buckets(object())  # type: ignore[arg-type]


def test_empirical_residual_reports_exact_observed_minus_expected_values() -> None:
    chain = validate_chain(_chain_records())

    result = empirical_residual(chain, expected="expected_iv")

    assert result.frame.get_column("iv_residual").to_list() == pytest.approx([0.04, -0.02])
    assert result.evidence.metrics["mean_residual"] == pytest.approx(0.01)
    assert result.evidence.metrics["median_residual"] == pytest.approx(0.01)
    assert result.evidence.metrics["rmse"] == pytest.approx(math.sqrt(0.001))
    assert result.evidence.metrics["positive_fraction"] == 0.5
    assert len(result.evidence.table("surface_groups")) == 1


def test_empirical_residual_rejects_missing_nonpositive_and_overwrite_contracts() -> None:
    chain = validate_chain(_chain_records())
    with pytest.raises(DataContractError, match="inputs are missing"):
        empirical_residual(chain, expected="missing")
    with pytest.raises(DataContractError, match="already exists"):
        empirical_residual(chain, expected="expected_iv", output="forward")

    records = _chain_records()
    records["expected_iv"][0] = 0.0
    with pytest.raises(DataContractError, match="must be positive"):
        empirical_residual(validate_chain(records), expected="expected_iv")
    with pytest.raises(MethodContractError, match="result of validate_chain"):
        empirical_residual(object())  # type: ignore[arg-type]
    with pytest.raises(MethodContractError, match="non-empty strings"):
        empirical_residual(chain, expected="")


@pytest.mark.parametrize("year_basis", [True, 0.0, float("nan")])
def test_validate_chain_rejects_invalid_year_basis(year_basis: object) -> None:
    with pytest.raises(MethodContractError, match="positive finite"):
        validate_chain(_chain_records(), year_basis=year_basis)  # type: ignore[arg-type]


@pytest.mark.parametrize("column", ["strike", "bid", "iv", "open_interest"])
def test_validate_chain_rejects_decimal_columns_with_a_data_contract_error_naming_column_and_dtype(
    column: str,
) -> None:
    # Contract: numeric fields must be float/integer; Decimal must not leak a raw Polars error.
    records = _chain_records()
    records.setdefault("open_interest", [10.0, 20.0])
    frame = pl.DataFrame(records).with_columns(pl.col(column).cast(pl.Decimal(18, 4)))

    with pytest.raises(DataContractError, match=rf"invalid dtypes: {column}=Decimal"):
        validate_chain(frame)


def test_empirical_residual_rejects_decimal_inputs_with_a_data_contract_error() -> None:
    # Contract: residual inputs follow the same float/integer-only rule as the chain.
    chain = validate_chain(_chain_records())
    frame = chain.frame.with_columns(pl.col("expected_iv").cast(pl.Decimal(18, 4)))
    decimal_chain = OptionChain(frame=frame, evidence=chain.evidence)

    with pytest.raises(DataContractError, match=r"invalid dtypes: expected_iv=Decimal"):
        empirical_residual(decimal_chain, expected="expected_iv")


def test_delta_buckets_labels_are_distinct_when_edges_differ_by_less_than_one_hundredth() -> None:
    # Contract: distinct edges must yield distinct bucket labels, so counts never merge buckets.
    records = _chain_records()
    records["delta"] = [0.001, 0.004]
    chain = validate_chain(records)

    result = delta_buckets(chain, edges=(0.0, 0.003, 0.004, 1.0))

    labels = result.frame.get_column("delta_bucket").to_list()
    assert labels == ["[0.000,0.003)", "[0.004,1.000]"]
    counts = {row["delta_bucket"]: row["quotes"] for row in result.evidence.table("bucket_counts")}
    assert counts == {"[0.000,0.003)": 1, "[0.004,1.000]": 1}
    assert result.evidence.metrics["occupied_buckets"] == 2


def test_delta_buckets_keep_two_decimal_labels_when_edges_are_already_distinct() -> None:
    # Stability contract: existing outputs do not change for edges distinct at two decimals.
    chain = validate_chain(_chain_records())

    result = delta_buckets(chain)

    assert result.frame.get_column("delta_bucket").to_list() == ["[0.40,0.60)", "[0.10,0.25)"]


def test_delta_buckets_labels_stay_distinct_for_edges_needing_extreme_precision() -> None:
    records = _chain_records()
    records["delta"] = [5e-301, 1.5e-300]
    chain = validate_chain(records)

    result = delta_buckets(chain, edges=(0.0, 1e-300, 2e-300, 1.0))

    labels = result.frame.get_column("delta_bucket").to_list()
    assert len(set(labels)) == 2
    assert labels[0] != labels[1]
    assert result.evidence.metrics["occupied_buckets"] == 2


@pytest.mark.parametrize("derived", ["forward", "time_to_expiry_years", "log_moneyness"])
def test_validate_chain_rejects_input_columns_that_collide_with_derived_columns(
    derived: str,
) -> None:
    # Contract: derived columns are never silently overwritten.
    records = _chain_records()
    records[derived] = [123.0, 456.0]

    with pytest.raises(DataContractError, match=rf"derived columns.*{derived}"):
        validate_chain(records)


def test_validate_chain_names_every_colliding_derived_column() -> None:
    records = _chain_records()
    records["forward"] = [1.0, 2.0]
    records["log_moneyness"] = [0.0, 0.0]

    with pytest.raises(DataContractError, match="forward, log_moneyness"):
        validate_chain(records)


def test_delta_buckets_rejects_existing_delta_bucket_column() -> None:
    # Contract: delta_bucket is derived; an input column of that name must not be overwritten.
    records = _chain_records()
    records["delta_bucket"] = ["mine", "mine"]
    chain = validate_chain(records)

    with pytest.raises(DataContractError, match="delta_bucket"):
        delta_buckets(chain)


@pytest.mark.parametrize("name", ["iv", "expected_iv"])
def test_empirical_residual_rejects_output_that_overwrites_an_input_column(name: str) -> None:
    # Contract: the residual output must not replace the observed or expected column.
    chain = validate_chain(_chain_records())

    with pytest.raises(MethodContractError, match="must not overwrite an input column"):
        empirical_residual(chain, observed="iv", expected="expected_iv", output=name)
    assert chain.frame.get_column(name).to_list() == _chain_records()[name]


def test_empirical_residual_input_overwrite_is_rejected_even_when_the_input_is_missing() -> None:
    chain = validate_chain(_chain_records())

    with pytest.raises(MethodContractError, match="must not overwrite an input column"):
        empirical_residual(chain, expected="absent", output="absent")


def test_option_chain_constructor_is_documented_as_unvalidated() -> None:
    # Contract (documented, behaviour unchanged): direct construction bypasses validation.
    assert OptionChain.__doc__ is not None
    assert "validate_chain" in OptionChain.__doc__
    assert "not validate" in OptionChain.__doc__.replace("\n", " ")
