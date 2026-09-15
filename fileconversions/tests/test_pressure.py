import numpy as np
import pytest

from mjolnir_fileconversions.errors import ConversionError, PressureEncodingError
from mjolnir_fileconversions.processing.pressure import (
    derive_hpa_aligned_levels,
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


def test_venus_hpa_grid_is_exact_unique_and_non_extrapolating():
    source = np.array(
        [
            99578.66,
            98740.38,
            97484.07,
            95036.73,
            90443.63,
            82394.24,
            69838.16,
            53397.42,
            36181.45,
            22012.64,
            12587.03,
            6976.137,
            3667.55,
            1772.695,
            764.7837,
            289.5211,
            98.61392,
            32.55017,
            11.16187,
            4.097814,
        ]
    )
    expected = np.array(
        [
            99500,
            98700,
            97500,
            95000,
            90400,
            82400,
            69800,
            53400,
            36200,
            22000,
            12600,
            7000,
            3700,
            1800,
            800,
            300,
            100,
        ]
    )
    target, rows = derive_hpa_aligned_levels(source)
    assert np.array_equal(target, expected)
    assert np.all(target % 100 == 0)
    assert target.max() <= source.max() and target.min() >= source.min()
    assert sum(row.target_emitted for row in rows) == 17
    assert [row.mapping_status for row in rows[-3:]] == [
        "omitted_duplicate_target",
        "omitted_duplicate_target",
        "omitted_duplicate_target",
    ]


def test_hpa_grid_uses_shared_column_bounds_and_ties_toward_lower_pressure():
    reference = np.array([100050.0, 50050.0, 50.0])
    columns = np.array(
        [
            [100020.0, 50000.0, 80.0],
            [99980.0, 49990.0, 120.0],
        ]
    )
    target, _ = derive_hpa_aligned_levels(reference, columns)
    assert np.array_equal(target, [99900, 50000, 200])
    assert target.max() <= np.min(np.max(columns, axis=-1))
    assert target.min() >= np.max(np.min(columns, axis=-1))


def test_log_pressure_missing_values_are_not_bridged():
    pressure = np.array([100000.0, 10000.0, 1000.0])
    field = np.array([[[1.0, np.nan, 3.0]]])
    result = interpolate_log_pressure(field, pressure, np.array([50000.0, 5000.0]))
    assert np.isnan(result).all()


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
