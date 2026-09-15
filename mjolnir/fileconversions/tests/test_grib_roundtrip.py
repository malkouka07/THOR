import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from mjolnir_fileconversions.models import CanonicalDataset
from mjolnir_fileconversions.processing.grid import target_regular_grid
from mjolnir_fileconversions.validation.grib_validation import (
    decode_grib_messages,
    roundtrip_against_canonical,
    validate_grib_files,
)
from mjolnir_fileconversions.writers.grib1_writer import (
    write_grib1_dataset,
    write_grib1_message,
)
from mjolnir_fileconversions.writers.grib2_writer_adapter import write_grib2_dataset


def canonical() -> CanonicalDataset:
    lat, lon = target_regular_grid(30, 60)
    level = np.array([100000, 50000])
    y = np.deg2rad(lat)[None, None, :, None]
    x = np.deg2rad(lon)[None, None, None, :]
    u = np.broadcast_to(np.cos(y) * np.cos(x), (1, 2, lat.size, lon.size)).copy()
    v = np.broadcast_to(np.cos(y) * np.sin(x), u.shape).copy()
    temperature = np.broadcast_to(
        250.0 + 5.0 * np.sin(y) + 2.0 * np.cos(y) * np.cos(x),
        u.shape,
    ).copy()
    return CanonicalDataset(
        np.array([0.0]),
        level,
        lat,
        lon,
        {
            "eastward_wind": u,
            "northward_wind": v,
            "air_temperature": temperature,
        },
        {
            "eastward_wind": "m s-1",
            "northward_wind": "m s-1",
            "air_temperature": "K",
        },
        metadata={"simulation_name": "test"},
    )


def test_grib1_write_read_roundtrip_and_parameters(tmp_path):
    dataset = canonical()
    paths, encoded = write_grib1_dataset(dataset, tmp_path)
    rows, _ = validate_grib_files(paths, expected_edition=1)
    roundtrip = roundtrip_against_canonical(
        paths,
        dataset,
        technical_epoch="2000-01-01T00:00:00Z",
        conversion_mode="test",
    )
    assert len(paths) == 3
    assert len(rows) == 6
    assert all(row["status"] == "passed" for row in rows)
    assert all(row["status"] == "passed" for row in roundtrip)
    assert sum(row["variable"] == "air_temperature" for row in roundtrip) == 2
    assert all(item.absolute_error_pa == 0 for item in encoded)
    temperature_messages = [
        item
        for item in decode_grib_messages(paths)
        if item.field_name == "air_temperature"
    ]
    assert len(temperature_messages) == 2
    assert all(
        item.metadata["table2Version"] == 2
        and item.metadata["indicatorOfParameter"] == 11
        and item.metadata["shortName"] == "t"
        and item.metadata["units"] == "K"
        and item.units == "K"
        for item in temperature_messages
    )
    assert all(np.allclose(item.values[0], 245.0) for item in temperature_messages)
    assert all(np.allclose(item.values[-1], 255.0) for item in temperature_messages)
    temperature_path = next(path for path in paths if "air_temperature" in path.name)
    sidecar = json.loads(
        Path(str(temperature_path) + ".metadata.json").read_text()
    )
    assert sidecar["elapsed_time_seconds"] == [0.0]
    assert sidecar["technical_epoch_utc"] == "2000-01-01T00:00:00Z"
    assert isinstance(sidecar["git_worktree_dirty"], bool)
    assert sidecar["grib_parameters"]["air_temperature"] == {
        "eccodes_param_id": 130,
        "grib1_wire_id": "11.2",
        "grib2_id": "0/0/0",
        "units": "K",
    }


def test_grib1_bitmap_roundtrip_preserves_missing_value(tmp_path):
    dataset = canonical().subset_fields(["eastward_wind"])
    dataset.fields["eastward_wind"][0, 0, 2, 2] = np.nan
    paths, _ = write_grib1_dataset(dataset, tmp_path)
    decoded = decode_grib_messages(paths)
    high_pressure = next(item for item in decoded if item.pressure_level_pa == 100000)
    assert np.isnan(high_pressure.values[2, 2])


def level_dependent_canonical() -> CanonicalDataset:
    lat, lon = target_regular_grid(30, 60)
    levels = np.array([100000, 50000, 10000])
    shape = (2, levels.size, lat.size, lon.size)
    base = np.broadcast_to(levels[None, :, None, None] / 1000.0, shape).copy()
    base[1] += 1.0
    return CanonicalDataset(
        np.array([0.0, 21600.0]),
        levels,
        lat,
        lon,
        {"eastward_wind": base, "northward_wind": -base},
        {"eastward_wind": "m s-1", "northward_wind": "m s-1"},
        metadata={"simulation_name": "ordered"},
    )


@pytest.mark.parametrize("edition", [1, 2])
@pytest.mark.parametrize("file_layout", ["per-variable", "per-time", "combined"])
def test_writers_emit_top_to_bottom_pressure_stacks_for_every_layout(
    tmp_path, edition, file_layout
):
    dataset = level_dependent_canonical()
    if edition == 1:
        paths, _ = write_grib1_dataset(
            dataset, tmp_path / "grib1", file_layout=file_layout
        )
    else:
        paths = write_grib2_dataset(
            dataset, tmp_path / "grib2", file_layout=file_layout
        )

    decoded = decode_grib_messages(paths)
    stacks: dict[tuple[Path, str, str], list[int]] = {}
    for item in decoded:
        stacks.setdefault((item.path, item.valid_time, item.field_name), []).append(
            item.pressure_level_pa
        )
        time_offset = 1.0 if item.valid_time == "20000101T0600" else 0.0
        expected = item.pressure_level_pa / 1000.0 + time_offset
        if item.field_name == "northward_wind":
            expected = -expected
        assert np.allclose(item.values, expected)

    assert len(stacks) == 4
    assert all(levels == [10000, 50000, 100000] for levels in stacks.values())
    rows, _ = validate_grib_files(paths, expected_edition=edition)
    assert all(row["status"] == "passed" for row in rows)
    assert {row["message_pressure_order"] for row in rows} == {"ascending"}
    for path in paths:
        sidecar = json.loads(Path(str(path) + ".metadata.json").read_text())
        assert sidecar["pressure_levels_pa"] == [100000, 50000, 10000]
        assert sidecar["message_pressure_order"] == "ascending_pa_top_to_bottom"
        assert sidecar["message_pressure_levels_pa"] == [10000, 50000, 100000]


def test_validation_rejects_descending_pressure_stack(tmp_path):
    dataset = level_dependent_canonical().subset_fields(["eastward_wind"])
    path = tmp_path / "descending.grib1"
    with path.open("wb") as stream:
        for level_index, level in enumerate(dataset.level_pa):
            write_grib1_message(
                stream,
                field_name="eastward_wind",
                values=dataset.fields["eastward_wind"][0, level_index],
                latitude=dataset.latitude,
                longitude=dataset.longitude,
                pressure_level_pa=level,
                valid=datetime(2000, 1, 1, tzinfo=timezone.utc),
                level_encoding="strict",
            )

    rows, _ = validate_grib_files([path], expected_edition=1)
    assert all(row["status"] == "failed" for row in rows)
    assert {row["message_pressure_order"] for row in rows} == {
        "not_strictly_ascending"
    }
    assert all("not strictly ascending" in row["warnings"] for row in rows)


def test_hpa_rounded_roundtrip_pairs_reordered_messages_by_pressure_rank(tmp_path):
    dataset = level_dependent_canonical().subset_fields(["eastward_wind"])
    dataset.level_pa = np.array([99578, 50040, 10040])
    paths, _ = write_grib1_dataset(
        dataset,
        tmp_path,
        level_encoding="hpa-rounded",
        max_relative_error=0.01,
    )

    rows = roundtrip_against_canonical(
        paths,
        dataset,
        technical_epoch="2000-01-01T00:00:00Z",
        conversion_mode="test hPa-rounded",
    )
    assert all(row["status"] == "passed" for row in rows)
