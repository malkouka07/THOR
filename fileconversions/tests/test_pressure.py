import numpy as np
import pytest

from mjolnir_fileconversions.errors import ConversionError, PressureEncodingError
from mjolnir_fileconversions.processing.pressure import (
    derive_integer_levels,
    interpolate_log_pressure,
    to_pa,
)
from mjolnir_fileconversions.writers.grib_common import encode_grib1_level


@pytest.mark.parametrize(
    "units,factor", [("Pa", 1), ("hPa", 100), ("mbar", 100), ("bar", 100000)]
)
def test_pressure_unit_conversion(units, factor):
    assert to_pa(np.array([1.0]), units)[0] == factor


def test_integer_level_mapping_is_reported():
    target, rows = derive_integer_levels(np.array([100000.2, 50000.4, 10000.1]))
    assert np.array_equal(target, [100000, 50000, 10000])
    assert rows[0].absolute_error_pa == pytest.approx(0.2)
    assert rows[0].interpolation_performed


def test_log_pressure_interpolation_and_no_extrapolation():
    pressure = np.array([100000.0, 10000.0, 1000.0])
    field = np.log(pressure)[None, None, :]
    target = np.array([50000.0, 5000.0])
    result = interpolate_log_pressure(field, pressure, target)
    assert np.allclose(result[0, 0], np.log(target))
    with pytest.raises(ConversionError, match="extrapolate"):
        interpolate_log_pressure(field, pressure, np.array([100.0]))


def test_grib1_strict_and_explicit_level_modes():
    exact = encode_grib1_level(50000, "strict")
    assert exact.encoded_level == 500
    assert exact.effective_pa == 50000
    with pytest.raises(PressureEncodingError, match="not exactly representable"):
        encode_grib1_level(50077, "strict")
    rounded = encode_grib1_level(
        50077, "hpa-rounded", max_absolute_error_pa=30, max_relative_error=0.01
    )
    assert rounded.effective_pa == 50100
    extended = encode_grib1_level(50077, "ecmwf-pa")
    assert extended.type_of_level == "isobaricInPa"
    with pytest.raises(PressureEncodingError, match="at most 65535"):
        encode_grib1_level(97895, "ecmwf-pa")
