from pathlib import Path

import numpy as np
import pytest

from mjolnir_fileconversions.models import SourceReferenceDataset
from mjolnir_fileconversions.validation import reconstruction
from mjolnir_fileconversions.validation.grib_validation import DecodedGribMessage
from mjolnir_fileconversions.validation.reporting import (
    with_difference_summary_rows,
)


SOURCE_PRESSURES = np.array([20000.0, 5000.0, 500.0, 50.0])
DECODED_PRESSURES = np.array([100, 1000, 10000])
SOURCE_LATITUDE = np.array([-45.0, 0.0, 45.0])
DECODED_LATITUDE = np.array([-90.0, 0.0, 90.0])
LONGITUDE = np.array([0.0, 120.0, 240.0])


def _log_pressure_field(pressures, offset):
    profile = offset + 2.5 * np.log(np.asarray(pressures, dtype=np.float64))
    return np.broadcast_to(
        profile[:, None, None],
        (profile.size, SOURCE_LATITUDE.size, LONGITUDE.size),
    ).copy()


def _source_reference():
    pressure = np.broadcast_to(
        SOURCE_PRESSURES[None, :, None, None],
        (1, SOURCE_PRESSURES.size, SOURCE_LATITUDE.size, LONGITUDE.size),
    ).copy()
    return SourceReferenceDataset(
        time_seconds=np.array([0.0]),
        latitude=SOURCE_LATITUDE,
        longitude=LONGITUDE,
        pressure_pa=pressure,
        fields={
            "eastward_wind": _log_pressure_field(
                SOURCE_PRESSURES, 10.0
            )[None, ...],
            "air_temperature": _log_pressure_field(
                SOURCE_PRESSURES, 250.0
            )[None, ...],
        },
        units={"eastward_wind": "m s-1", "air_temperature": "K"},
        source_files=[Path("regrid_test_0.h5")],
        source_dataset_names={
            "eastward_wind": "U",
            "air_temperature": "Temperature",
        },
    )


def _decoded_messages():
    messages = []
    message_index = 0
    for field_name, offset, units in (
        ("eastward_wind", 10.0, "m s-1"),
        ("air_temperature", 250.0, "K"),
    ):
        # The physical message order is deliberately top-to-bottom (ascending
        # pressure), while the source HDF5 levels are bottom-to-top.  Correct
        # reconstruction must use semantic pressure values, not indices.
        for pressure in DECODED_PRESSURES:
            message_index += 1
            values = np.full(
                (DECODED_LATITUDE.size, LONGITUDE.size),
                offset + 2.5 * np.log(pressure),
            )
            messages.append(
                DecodedGribMessage(
                    path=Path(f"test_{field_name}.grib1"),
                    message_index=message_index,
                    edition=1,
                    field_name=field_name,
                    units=units,
                    pressure_level_pa=int(pressure),
                    valid_time="20000101T0000",
                    latitude=DECODED_LATITUDE,
                    longitude=LONGITUDE,
                    values=values,
                    metadata={},
                )
            )
    return messages


@pytest.fixture
def reconstruction_result(monkeypatch):
    monkeypatch.setattr(
        reconstruction, "decode_grib_messages", lambda paths: _decoded_messages()
    )
    source = _source_reference()
    result = reconstruction.reconstruct_grib_on_source_grid(
        [Path("semantic-order-test.grib1")],
        source,
        technical_epoch="2000-01-01T00:00:00Z",
    )
    return source, result


def test_log_pressure_reconstruction_matches_semantic_levels(
    reconstruction_result,
):
    source, result = reconstruction_result

    assert np.array_equal(
        result.decoded_levels_pa[(0, "eastward_wind")], DECODED_PRESSURES
    )
    for field_name in source.fields:
        reconstructed = result.reconstructed[field_name][0]
        assert np.allclose(
            reconstructed[1:3], source.fields[field_name][0, 1:3], atol=1e-12
        )


def test_out_of_range_source_levels_are_not_extrapolated(
    reconstruction_result,
):
    _, result = reconstruction_result

    for reconstructed in result.reconstructed.values():
        assert np.isnan(reconstructed[0, 0]).all()
        assert np.isnan(reconstructed[0, 3]).all()

    all_region = [
        row
        for row in result.rows
        if row["variable"] == "eastward_wind" and row["region"] == "all"
    ]
    assert [row["status"] for row in all_region] == [
        "not_comparable",
        "measured",
        "measured",
        "not_comparable",
    ]
    for row in (all_region[0], all_region[-1]):
        assert row["compared_value_count"] == 0
        assert row["pressure_in_range_count"] == 0
        assert row["excluded_pressure_count"] == 9
        assert "outside" in row["reason"]


def test_temperature_is_reconstructed_and_reported(reconstruction_result):
    source, result = reconstruction_result

    assert set(result.reconstructed) == {"eastward_wind", "air_temperature"}
    temperature_rows = [
        row for row in result.rows if row["variable"] == "air_temperature"
    ]
    assert temperature_rows
    assert {row["units"] for row in temperature_rows} == {"K"}
    assert {row["source_dataset"] for row in temperature_rows} == {
        "Temperature"
    }
    assert np.allclose(
        result.reconstructed["air_temperature"][0, 1:3],
        source.fields["air_temperature"][0, 1:3],
        atol=1e-12,
    )


def test_reconstruction_rows_integrate_with_weighted_csv_summaries(
    reconstruction_result,
):
    _, result = reconstruction_result

    summarized = with_difference_summary_rows(
        result.rows,
        group_fields=("comparison_stage", "region"),
        count_field="compared_value_count",
    )
    details = summarized[: len(result.rows)]
    summaries = summarized[len(result.rows) :]

    assert all(row["row_type"] == "detail" for row in details)
    assert summaries
    assert all(row["row_type"] == "summary" for row in summaries)
    assert {
        (row["variable"], row["units"]) for row in summaries
    } == {("eastward_wind", "m s-1"), ("air_temperature", "K")}
    all_temperature = next(
        row
        for row in summaries
        if row["variable"] == "air_temperature" and row["region"] == "all"
    )
    assert all_temperature["compared_value_count"] == 18
    assert all_temperature["maximum_absolute_difference"] < 1e-12
    assert all_temperature["mean_absolute_difference"] < 1e-12
