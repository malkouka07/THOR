import csv
from types import SimpleNamespace

import numpy as np
import pytest

from mjolnir_fileconversions.commands import compare_command
from mjolnir_fileconversions.errors import ConversionError
from mjolnir_fileconversions.validation.parity import compare_grib_collections
from mjolnir_fileconversions.writers.grib1_writer import write_grib1_dataset
from mjolnir_fileconversions.writers.grib2_writer_adapter import write_grib2_dataset

from test_grib_roundtrip import canonical


def test_same_canonical_fields_have_packing_parity(tmp_path):
    grib1, _ = write_grib1_dataset(canonical(), tmp_path / "g1")
    grib2 = write_grib2_dataset(canonical(), tmp_path / "g2")
    rows = compare_grib_collections(grib1, grib2, packing_tolerance=1e-5)
    assert len(rows) == 6
    temperature = [row for row in rows if row["variable"] == "air_temperature"]
    assert len(temperature) == 2
    assert {row["units"] for row in temperature} == {"K"}
    assert {row["percentage_reference"] for row in rows} == {"decoded_grib2"}
    assert all(row["reference_maximum_absolute_value"] > 0 for row in temperature)
    assert all(row["parity_status"] == "passed" for row in rows)
    assert max(row["max_absolute_difference"] for row in rows) <= 1e-5


def test_compare_command_appends_per_variable_summary_rows(tmp_path):
    grib1_dir = tmp_path / "g1"
    grib2_dir = tmp_path / "g2"
    write_grib1_dataset(canonical(), grib1_dir)
    write_grib2_dataset(canonical(), grib2_dir)
    report = tmp_path / "parity.csv"

    detail = compare_command(
        SimpleNamespace(
            grib1_dir=grib1_dir,
            grib2_dir=grib2_dir,
            grib1_glob="*.grib1",
            grib2_glob="*.grib2",
            packing_tolerance=1e-5,
            report=report,
        )
    )

    with report.open(newline="", encoding="utf-8") as stream:
        written = list(csv.DictReader(stream))
    assert len(detail) == 6
    assert [row["row_type"] for row in written[-3:]] == ["summary"] * 3
    assert {row["variable"] for row in written[-3:]} == {
        "eastward_wind",
        "northward_wind",
        "air_temperature",
    }
    assert {row["percentage_reference"] for row in written[-3:]} == {
        "decoded_grib2"
    }
    assert all(
        row["maximum_absolute_difference_percent_of_reference_maximum"]
        for row in written[-3:]
    )
    assert all(
        row["mean_absolute_difference_percent_of_reference_mean_absolute"]
        for row in written[-3:]
    )


def test_parity_rejects_temperature_missing_from_only_one_edition(tmp_path):
    grib1, _ = write_grib1_dataset(
        canonical().subset_fields(["eastward_wind", "northward_wind"]),
        tmp_path / "g1",
    )
    grib2 = write_grib2_dataset(canonical(), tmp_path / "g2")

    with pytest.raises(ConversionError, match="key sets differ"):
        compare_grib_collections(grib1, grib2)


def test_parity_fails_when_missing_value_masks_differ(tmp_path):
    grib1_dataset = canonical().subset_fields(["eastward_wind"])
    grib2_dataset = canonical().subset_fields(["eastward_wind"])
    grib1_dataset.fields["eastward_wind"][0, 0, 2, 2] = np.nan
    grib1, _ = write_grib1_dataset(grib1_dataset, tmp_path / "g1")
    grib2 = write_grib2_dataset(grib2_dataset, tmp_path / "g2")

    rows = compare_grib_collections(grib1, grib2)
    mismatched = next(row for row in rows if row["pressure_level_pa"] == 100000)
    assert mismatched["missing_mask_mismatch_count"] == 1
    assert mismatched["parity_status"] == "failed"
