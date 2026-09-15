import numpy as np
import pytest
import xarray as xr

from mjolnir_fileconversions.errors import ConversionError, ScientificMappingError
from mjolnir_fileconversions.readers.netcdf_reader import read_netcdf
from mjolnir_fileconversions.validation.grib_validation import (
    decode_grib_messages,
    validate_grib_files,
)
from mjolnir_fileconversions.writers.grib1_writer import write_grib1_dataset


def test_aliases_and_dimension_transpose_without_double_regrid(tmp_path):
    lat = np.array([-90.0, -45.0, 0.0, 45.0, 90.0])
    lon = np.arange(0.0, 360.0, 60.0)
    lev = np.array([100000, 50000], dtype=np.int32)
    values = np.arange(60.0).reshape(6, 5, 2, 1)
    dataset = xr.Dataset(
        {
            "u": (("lon", "lat", "plev", "Time"), values),
            "v": (("lon", "lat", "plev", "Time"), values + 1),
            "Temperature": (
                ("lon", "lat", "plev", "Time"),
                values + 250.0,
                {"standard_name": "air_temperature", "units": "K"},
            ),
            "omega": (("lon", "lat", "plev", "Time"), values / 10, {"standard_name": "lagrangian_tendency_of_air_pressure", "units": "Pa s-1"}),
        },
        coords={
            "lat": ("lat", lat, {"standard_name": "latitude", "units": "degrees_north"}),
            "lon": ("lon", lon, {"standard_name": "longitude", "units": "degrees_east"}),
            "plev": ("plev", lev, {"standard_name": "air_pressure", "units": "Pa", "axis": "Z"}),
            "Time": ("Time", [0.0], {"units": "seconds since 2000-01-01", "axis": "T"}),
        },
    )
    path = tmp_path / "aliases.nc"
    dataset.to_netcdf(path)
    result, _ = read_netcdf(
        path,
        lat_step=45,
        lon_step=60,
        regrid="if-needed",
        vertical_velocity_mode="strict",
    )
    assert result.shape == (1, 2, 5, 6)
    assert set(result.fields) == {
        "eastward_wind",
        "northward_wind",
        "air_temperature",
        "omega",
    }
    assert result.units["air_temperature"] == "K"
    assert np.array_equal(result.level_pa, lev)
    outputs, _ = write_grib1_dataset(result, tmp_path / "grib1")
    rows, _ = validate_grib_files(outputs, expected_edition=1)
    assert len(rows) == 8
    assert all(row["status"] == "passed" for row in rows)
    temperature = [
        item
        for item in decode_grib_messages(outputs)
        if item.field_name == "air_temperature"
    ]
    assert len(temperature) == 2
    assert all(
        item.metadata["indicatorOfParameter"] == 11
        and item.metadata["units"] == "K"
        for item in temperature
    )


def test_time_indices_limit_the_loaded_netcdf_slice(tmp_path):
    lat = np.array([-90.0, 0.0, 90.0])
    lon = np.array([0.0, 120.0, 240.0])
    lev = np.array([100000], dtype=np.int32)
    values = np.arange(18.0).reshape(2, 1, 3, 3)
    dataset = xr.Dataset(
        {
            "u": (("time", "level", "lat", "lon"), values),
            "v": (("time", "level", "lat", "lon"), values + 1),
        },
        coords={
            "time": ("time", [0.0, 3600.0], {"units": "seconds since technical epoch"}),
            "level": ("level", lev, {"units": "Pa", "axis": "Z"}),
            "lat": ("lat", lat, {"standard_name": "latitude"}),
            "lon": ("lon", lon, {"standard_name": "longitude"}),
        },
    )
    path = tmp_path / "times.nc"
    dataset.to_netcdf(path)
    result, _ = read_netcdf(
        path,
        variables=["u", "v"],
        lat_step=90,
        lon_step=120,
        regrid="never",
        time_indices=[1],
    )
    assert result.time_seconds.tolist() == [3600.0]
    assert np.array_equal(result.fields["eastward_wind"][0], values[1])


def test_netcdf_hpa_policy_interpolates_values_not_only_level_labels(tmp_path):
    lat = np.array([-90.0, 0.0, 90.0])
    lon = np.array([0.0, 120.0, 240.0])
    level = np.array([99578.0, 50040.0, 98.0])
    base = np.log(level)[None, :, None, None]
    shape = (2, level.size, lat.size, lon.size)
    u = np.broadcast_to(base, shape).copy()
    source = xr.Dataset(
        {
            "u": (("time", "level", "lat", "lon"), u),
            "v": (("time", "level", "lat", "lon"), 2.0 * u),
            "temperature": (
                ("time", "level", "lat", "lon"),
                220.0 + u,
                {"standard_name": "air_temperature", "units": "K"},
            ),
            "omega": (
                ("time", "level", "lat", "lon"),
                -3.0 * u,
                {
                    "standard_name": "lagrangian_tendency_of_air_pressure",
                    "units": "Pa s-1",
                },
            ),
        },
        coords={
            "time": ("time", [0.0, 86400.0], {"units": "seconds since technical epoch"}),
            "level": ("level", level, {"units": "Pa", "axis": "Z"}),
            "lat": ("lat", lat, {"standard_name": "latitude"}),
            "lon": ("lon", lon, {"standard_name": "longitude"}),
        },
    )
    path = tmp_path / "log_pressure.nc"
    source.to_netcdf(path)

    result, _ = read_netcdf(
        path,
        lat_step=90,
        lon_step=120,
        regrid="never",
        pressure_level_policy="hpa-aligned",
    )

    assert np.array_equal(result.level_pa, [99500, 50000, 100])
    assert np.allclose(
        result.fields["eastward_wind"],
        np.log(result.level_pa)[None, :, None, None],
        atol=1e-12,
    )
    assert np.allclose(
        result.fields["air_temperature"],
        220.0 + np.log(result.level_pa)[None, :, None, None],
        atol=1e-12,
    )
    assert result.time_seconds.tolist() == [0.0, 86400.0]
    assert result.units["air_temperature"] == "K"
    assert result.units["omega"] == "Pa s-1"
    assert result.metadata["vertical_interpolation_count"] == 1


def _temperature_dataset(units: str | None = "K") -> xr.Dataset:
    latitude = np.array([-60.0, 0.0, 60.0])
    longitude = np.array([0.0, 90.0, 180.0, 270.0])
    values = np.array(
        [
            [
                [
                    [210.0, 220.0, 230.0, 240.0],
                    [240.0, 250.0, 260.0, 270.0],
                    [270.0, 280.0, 290.0, 300.0],
                ]
            ]
        ]
    )
    attrs = {"standard_name": "air_temperature"}
    if units is not None:
        attrs["units"] = units
    return xr.Dataset(
        {"Temperature": (("time", "level", "lat", "lon"), values, attrs)},
        coords={
            "time": ("time", [0.0], {"units": "seconds since technical epoch"}),
            "level": ("level", [50000], {"units": "Pa", "axis": "Z"}),
            "lat": ("lat", latitude, {"standard_name": "latitude"}),
            "lon": ("lon", longitude, {"standard_name": "longitude"}),
        },
    )


def test_temperature_only_is_requested_independently_and_uses_scalar_poles(tmp_path):
    path = tmp_path / "temperature_only.nc"
    _temperature_dataset().to_netcdf(path)

    result, _ = read_netcdf(
        path,
        variables=["t"],
        lat_step=30,
        lon_step=90,
        regrid="if-needed",
    )

    assert set(result.fields) == {"air_temperature"}
    assert result.units == {"air_temperature": "K"}
    temperature = result.fields["air_temperature"][0, 0]
    assert np.allclose(temperature[0], 225.0)
    assert np.allclose(temperature[-1], 285.0)
    assert np.array_equal(temperature[3], [240.0, 250.0, 260.0, 270.0])
    assert result.stages[0].detected_vector_stage == "not_applicable_scalar"
    assert "vector rotation" not in result.stages[0].skipped_as_already_completed


@pytest.mark.parametrize("units", [None, "degree_Celsius", "m s-1"])
def test_temperature_requires_kelvin_units(tmp_path, units):
    path = tmp_path / "wrong_temperature_units.nc"
    _temperature_dataset(units).to_netcdf(path)

    with pytest.raises(ConversionError, match="must use Kelvin units"):
        read_netcdf(
            path,
            variables=["temperature"],
            lat_step=30,
            lon_step=90,
        )


def test_missing_requested_temperature_fails_clearly(tmp_path):
    source = _temperature_dataset().drop_vars("Temperature")
    source["u"] = (
        ("time", "level", "lat", "lon"),
        np.ones((1, 1, 3, 4)),
    )
    path = tmp_path / "no_temperature.nc"
    source.to_netcdf(path)

    with pytest.raises(
        ScientificMappingError,
        match="requested field air_temperature could not be identified",
    ):
        read_netcdf(
            path,
            variables=["temperature"],
            lat_step=30,
            lon_step=90,
        )
