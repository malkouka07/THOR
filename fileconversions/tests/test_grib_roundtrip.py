from pathlib import Path

import numpy as np

from mjolnir_fileconversions.models import CanonicalDataset
from mjolnir_fileconversions.processing.grid import target_regular_grid
from mjolnir_fileconversions.validation.grib_validation import (
    decode_grib_messages,
    roundtrip_against_canonical,
    validate_grib_files,
)
from mjolnir_fileconversions.writers.grib1_writer import write_grib1_dataset


def canonical() -> CanonicalDataset:
    lat, lon = target_regular_grid(30, 60)
    level = np.array([100000, 50000])
    y = np.deg2rad(lat)[None, None, :, None]
    x = np.deg2rad(lon)[None, None, None, :]
    u = np.broadcast_to(np.cos(y) * np.cos(x), (1, 2, lat.size, lon.size)).copy()
    v = np.broadcast_to(np.cos(y) * np.sin(x), u.shape).copy()
    return CanonicalDataset(
        np.array([0.0]),
        level,
        lat,
        lon,
        {"eastward_wind": u, "northward_wind": v},
        {"eastward_wind": "m s-1", "northward_wind": "m s-1"},
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
    assert len(paths) == 2
    assert len(rows) == 4
    assert all(row["status"] == "passed" for row in rows)
    assert all(row["status"] == "passed" for row in roundtrip)
    assert all(item.absolute_error_pa == 0 for item in encoded)


def test_grib1_bitmap_roundtrip_preserves_missing_value(tmp_path):
    dataset = canonical().subset_fields(["eastward_wind"])
    dataset.fields["eastward_wind"][0, 0, 2, 2] = np.nan
    paths, _ = write_grib1_dataset(dataset, tmp_path)
    decoded = decode_grib_messages(paths)
    assert np.isnan(decoded[0].values[2, 2])
