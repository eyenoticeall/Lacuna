from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from lacuna.exceptions import DataContractError
from lacuna.experiment import (
    _streaming_canonical_json,
    _streaming_fingerprint,
    canonical_json,
    fingerprint,
)

JSON_VALUES = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**63), max_value=2**63 - 1)
    | st.floats(allow_nan=False, allow_infinity=False, width=64)
    | st.text(),
    lambda children: (
        st.lists(children, max_size=8)
        | st.dictionaries(
            st.text(min_size=1).filter(
                lambda key: (
                    not any(
                        key.casefold().replace("-", "_").endswith(suffix)
                        for suffix in (
                            "access_key",
                            "api_key",
                            "authorization",
                            "cookie",
                            "credential",
                            "password",
                            "secret",
                            "token",
                        )
                    )
                )
            ),
            children,
            max_size=8,
        )
    ),
    max_leaves=40,
)


@given(JSON_VALUES)
def test_streaming_encoder_is_byte_identical_to_c14n_v1(value: object) -> None:
    assert _streaming_canonical_json(value) == canonical_json(value)
    assert _streaming_fingerprint(value, namespace="property") == fingerprint(
        value, namespace="property"
    )


@pytest.mark.parametrize(
    ("value", "expected_json", "expected_digest"),
    [
        (
            {
                "z": -0.0,
                "a": "café",
                "time": datetime(2026, 8, 27, 3, 4, 5, 123456, tzinfo=UTC),
                "date": date(2026, 8, 27),
            },
            '{"a":"café","date":"2026-08-27","time":"2026-08-27T03:04:05.123456Z","z":0.0}',
            "sha256:c14n-v1:841e99ddf1568620ff2a752e050ad32f6eecc340c570355551c38669276aa024",
        ),
        (
            [None, True, False, 1, -2, 1e-7, 1e20, 1.2345678901234567],
            "[null,true,false,1,-2,1e-07,1e+20,1.2345678901234567]",
            "sha256:c14n-v1:380530363cdc431bb5c7e538ec0f3064ab436a6d22ad161f4aa68f5901a21780",
        ),
        (
            {"nested": {"β": [1, 2, 3], "alpha": {"x": 'line\\nquote\\"'}}},
            '{"nested":{"alpha":{"x":"line\\\\nquote\\\\\\""},"β":[1,2,3]}}',
            "sha256:c14n-v1:5e5f419a59097d2bc27acf14cd0db5652eb2477ab29c641e6eb65f43993cdd80",
        ),
    ],
)
def test_streaming_encoder_matches_frozen_c14n_v1_corpus(
    value: object, expected_json: str, expected_digest: str
) -> None:
    assert _streaming_canonical_json(value) == expected_json
    assert _streaming_fingerprint(value, namespace="frozen-corpus") == expected_digest


def test_streaming_encoder_handles_arrays_without_tolist_intermediates() -> None:
    values = np.asarray([[0.0, -0.0, 1.5], [2.0, 3.0, 4.0]], dtype=np.float64)
    assert _streaming_canonical_json(values) == canonical_json(values.tolist())
    assert _streaming_fingerprint(values, namespace="array") == fingerprint(
        values.tolist(), namespace="array"
    )
    assert fingerprint(values, namespace="array") == fingerprint(values.tolist(), namespace="array")
    for layout in (np.asfortranarray(values), values[:, ::-1][:, ::-1]):
        assert fingerprint(layout, namespace="array") == fingerprint(
            values.tolist(), namespace="array"
        )


def test_streaming_encoder_handles_empty_and_signed_zero_arrays() -> None:
    empty = np.empty((0, 3), dtype=np.float64)
    signed_zero = np.asarray([-0.0, 0.0], dtype=np.float64)
    assert fingerprint(empty, namespace="array") == fingerprint([], namespace="array")
    assert fingerprint(signed_zero, namespace="array") == fingerprint([0.0, 0.0], namespace="array")


def test_streaming_encoder_handles_frame_rows_and_chunk_layouts() -> None:
    first = pl.DataFrame(
        {
            "time": [date(2026, 1, 1), date(2026, 1, 2)],
            "instrument": pl.Series(["A", "B"], dtype=pl.Categorical),
            "value": [1.0, None],
            "nested": [[1, 2], [3]],
        }
    )
    chunked = pl.concat([first.head(1), first.tail(1)], rechunk=False)

    expected = canonical_json(first.to_dicts())
    assert _streaming_canonical_json(first) == expected
    assert _streaming_canonical_json(chunked) == expected
    assert _streaming_fingerprint(first, namespace="frame") == _streaming_fingerprint(
        chunked, namespace="frame"
    )
    assert fingerprint(first, namespace="frame") == fingerprint(first.to_dicts(), namespace="frame")
    assert fingerprint(first.select(reversed(first.columns)), namespace="frame") == fingerprint(
        first, namespace="frame"
    )
    assert fingerprint(first.reverse(), namespace="frame") != fingerprint(first, namespace="frame")


@pytest.mark.parametrize("value", [b"binary", {"nested": [b"binary"]}])
def test_streaming_encoder_preserves_binary_rejection(value: object) -> None:
    with pytest.raises(DataContractError, match="unsupported value type bytes"):
        _streaming_canonical_json(value)
    with pytest.raises(DataContractError, match="unsupported value type bytes"):
        fingerprint(pl.DataFrame({"payload": [b"binary"]}), namespace="binary-frame")


def test_streaming_encoder_distinguishes_null_and_rejects_nonfinite() -> None:
    assert _streaming_canonical_json([None]) == "[null]"
    with pytest.raises(DataContractError, match="NaN or infinity"):
        _streaming_canonical_json(np.asarray([np.nan]))
