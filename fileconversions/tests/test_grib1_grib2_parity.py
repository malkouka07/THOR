from mjolnir_fileconversions.validation.parity import compare_grib_collections
from mjolnir_fileconversions.writers.grib1_writer import write_grib1_dataset
from mjolnir_fileconversions.writers.grib2_writer_adapter import write_grib2_dataset

from test_grib_roundtrip import canonical


def test_same_canonical_fields_have_packing_parity(tmp_path):
    grib1, _ = write_grib1_dataset(canonical(), tmp_path / "g1")
    grib2 = write_grib2_dataset(canonical(), tmp_path / "g2")
    rows = compare_grib_collections(grib1, grib2, packing_tolerance=1e-5)
    assert rows
    assert all(row["parity_status"] == "passed" for row in rows)
    assert max(row["max_absolute_difference"] for row in rows) <= 1e-5
