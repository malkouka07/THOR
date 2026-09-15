from datetime import datetime, timezone

import numpy as np
import pytest

from mjolnir_fileconversions.errors import ConversionError, UnsupportedMessageError
from mjolnir_fileconversions.models import CanonicalDataset, PlanetParameters
from mjolnir_fileconversions.processing.grid import target_regular_grid
from mjolnir_fileconversions.readers.grib2_reader import (
    iter_grib2,
    read_grib2_collection,
)
from mjolnir_fileconversions.validation.grib_validation import decode_grib_messages
from mjolnir_fileconversions.writers.grib1_writer import write_grib1_dataset
from mjolnir_fileconversions.writers.grib2_writer_adapter import write_grib2_dataset
from mjolnir_fileconversions.writers.grib_common import (
    eccodes_module,
    set_regular_grid,
    set_valid_time,
    set_values,
)

from test_grib_roundtrip import canonical


def test_grib2_message_mapping(tmp_path):
    paths = write_grib2_dataset(canonical(), tmp_path)
    messages = [message for path in paths for message in iter_grib2(path)]
    assert len(messages) == 4
    assert {item.field_name for item in messages} == {"eastward_wind", "northward_wind"}
    assert {item.pressure_level_pa for item in messages} == {100000, 50000}


def test_grib2_collection_interpolates_stacks_and_retains_native_times(tmp_path):
    latitude, longitude = target_regular_grid(30, 60)
    source_level = np.array([99578, 50040, 98])
    base = np.log(source_level)[None, :, None, None]
    shape = (2, source_level.size, latitude.size, longitude.size)
    u = np.broadcast_to(base, shape).copy()
    source = CanonicalDataset(
        time_seconds=np.array([0.0, 21600.0]),
        level_pa=source_level,
        latitude=latitude,
        longitude=longitude,
        fields={
            "eastward_wind": u,
            "northward_wind": 2.0 * u,
            "omega": -3.0 * u,
        },
        units={
            "eastward_wind": "m s-1",
            "northward_wind": "m s-1",
            "omega": "Pa s-1",
        },
        planet=PlanetParameters(name="Venus", gravity_m_s2=8.87),
        metadata={"simulation_name": "stack"},
    )
    grib2_paths = write_grib2_dataset(source, tmp_path / "grib2")

    converted, mapping, _ = read_grib2_collection(
        grib2_paths, pressure_level_policy="hpa-aligned"
    )

    assert np.array_equal(converted.level_pa, [99500, 50000, 100])
    assert np.allclose(
        converted.fields["eastward_wind"],
        np.log(converted.level_pa)[None, :, None, None],
        atol=2e-6,
    )
    assert converted.metadata["absolute_valid_times_utc"] == [
        "2000-01-01T00:00:00Z",
        "2000-01-01T06:00:00Z",
    ]
    assert converted.metadata["vertical_interpolation_count"] == 1
    assert converted.planet.name == "Venus"
    assert converted.planet.gravity_m_s2 == 8.87
    assert all(row.grib1_exactly_representable for row in mapping)

    grib1_paths, _ = write_grib1_dataset(converted, tmp_path / "grib1")
    decoded = decode_grib_messages(grib1_paths)
    assert {item.valid_time for item in decoded} == {
        "20000101T0000",
        "20000101T0600",
    }
    assert {item.pressure_level_pa for item in decoded} == {99500, 50000, 100}
    omega = [item for item in decoded if item.field_name == "omega"]
    assert omega and all(item.metadata["indicatorOfParameter"] == 39 for item in omega)
    assert all(item.metadata["table2Version"] == 2 for item in omega)
    assert all("Pa" in str(item.metadata["units"]) for item in omega)


def test_grib2_height_above_ground_is_never_treated_as_pressure(tmp_path):
    codes = eccodes_module()
    latitude, longitude = target_regular_grid(30, 60)
    path = tmp_path / "ten_metre_u.grib2"
    handle = codes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        codes.codes_set(handle, "discipline", 0)
        codes.codes_set(handle, "parameterCategory", 2)
        codes.codes_set(handle, "parameterNumber", 2)
        codes.codes_set(handle, "typeOfLevel", "heightAboveGround")
        codes.codes_set(handle, "level", 10)
        set_regular_grid(codes, handle, latitude, longitude)
        set_valid_time(codes, handle, datetime(2000, 1, 1, tzinfo=timezone.utc))
        set_values(codes, handle, np.ones((latitude.size, longitude.size)), 24)
        with path.open("wb") as stream:
            codes.codes_write(handle, stream)
    finally:
        codes.codes_release(handle)

    with pytest.raises(UnsupportedMessageError, match="Only isobaric"):
        list(iter_grib2(path))
    skipped = list(iter_grib2(path, on_unsupported="skip"))
    assert len(skipped) == 1
    assert skipped[0].field_name == ""
    assert skipped[0].pressure_level_pa is None


def test_grib2_bitmap_is_preserved_through_pressure_interpolation(tmp_path):
    latitude, longitude = target_regular_grid(30, 60)
    source_level = np.array([100020, 50040, 9990])
    values = np.broadcast_to(
        np.log(source_level)[None, :, None, None],
        (1, source_level.size, latitude.size, longitude.size),
    ).copy()
    values[0, 1, 2, 2] = np.nan
    source = CanonicalDataset(
        time_seconds=np.array([0.0]),
        level_pa=source_level,
        latitude=latitude,
        longitude=longitude,
        fields={"eastward_wind": values},
        units={"eastward_wind": "m s-1"},
        metadata={"simulation_name": "bitmap"},
    )
    paths = write_grib2_dataset(source, tmp_path / "bitmap_grib2")

    messages = [message for path in paths for message in iter_grib2(path)]
    middle = next(item for item in messages if item.pressure_level_pa == 50040)
    assert np.isnan(middle.values[2, 2])

    converted, _, _ = read_grib2_collection(paths)
    assert np.array_equal(converted.level_pa, [100000, 50000, 10000])
    assert np.isnan(converted.fields["eastward_wind"][0, :, 2, 2]).all()
    assert np.isfinite(converted.fields["eastward_wind"][0, :, 2, 3]).all()


def test_grib2_subminute_validity_time_is_rejected(tmp_path):
    codes = eccodes_module()
    latitude, longitude = target_regular_grid(30, 60)
    path = tmp_path / "seconds.grib2"
    handle = codes.codes_grib_new_from_samples("regular_ll_pl_grib2")
    try:
        codes.codes_set(handle, "discipline", 0)
        codes.codes_set(handle, "parameterCategory", 2)
        codes.codes_set(handle, "parameterNumber", 2)
        codes.codes_set(handle, "typeOfLevel", "isobaricInPa")
        codes.codes_set(handle, "level", 50000)
        set_regular_grid(codes, handle, latitude, longitude)
        set_valid_time(codes, handle, datetime(2000, 1, 1, tzinfo=timezone.utc))
        codes.codes_set(handle, "second", 30)
        set_values(codes, handle, np.ones((latitude.size, longitude.size)), 24)
        with path.open("wb") as stream:
            codes.codes_write(handle, stream)
    finally:
        codes.codes_release(handle)

    with pytest.raises(ConversionError, match="sub-minute"):
        list(iter_grib2(path))
