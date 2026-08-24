from mjolnir_fileconversions.readers.grib2_reader import iter_grib2
from mjolnir_fileconversions.writers.grib2_writer_adapter import write_grib2_dataset

from test_grib_roundtrip import canonical


def test_grib2_message_mapping(tmp_path):
    paths = write_grib2_dataset(canonical(), tmp_path)
    messages = [message for path in paths for message in iter_grib2(path)]
    assert len(messages) == 4
    assert {item.field_name for item in messages} == {"eastward_wind", "northward_wind"}
    assert {item.pressure_level_pa for item in messages} == {100000, 50000}
