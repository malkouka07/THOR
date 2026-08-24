"""CF-aware NetCDF adapter to the shared canonical pressure-grid model."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import xarray as xr

from ..errors import ConversionError, ScientificMappingError
from ..models import CanonicalDataset, PlanetParameters, ProcessingStage
from ..processing.grid import (
    grids_equal,
    horizontal_remap,
    normalize_source_grid,
    target_regular_grid,
)
from ..processing.pressure import PressureMapping, derive_integer_levels, interpolate_log_pressure, to_pa
from ..processing.vertical_velocity import resolve_omega


COORD_ALIASES = {
    "latitude": {"lat", "latitude", "lats"},
    "longitude": {"lon", "longitude", "lons"},
    "level": {"level", "lev", "plev", "pressure", "pres"},
    "time": {"time", "Time", "t"},
}

FIELD_ALIASES = {
    "eastward_wind": {"u", "U", "eastward_wind", "zonal_wind"},
    "northward_wind": {"v", "V", "northward_wind", "meridional_wind"},
    "omega": {"omega", "lagrangian_tendency_of_air_pressure"},
    "geometric_w": {"w", "W", "upward_air_velocity", "vertical_velocity"},
    "density": {"rho", "Rho", "air_density", "density"},
}


def _coord(dataset: xr.Dataset, role: str) -> str:
    for name, variable in dataset.variables.items():
        attrs = variable.attrs
        if (
            name in COORD_ALIASES[role]
            or attrs.get("standard_name") == role
            or attrs.get("axis", "").upper() == {"latitude": "Y", "longitude": "X", "level": "Z", "time": "T"}[role]
        ):
            if variable.ndim == 1:
                return name
    raise ConversionError(f"cannot identify NetCDF {role} coordinate")


def _field(dataset: xr.Dataset, role: str) -> str | None:
    standards = {
        "eastward_wind": "eastward_wind",
        "northward_wind": "northward_wind",
        "omega": "lagrangian_tendency_of_air_pressure",
        "geometric_w": "upward_air_velocity",
        "density": "air_density",
    }
    for name, variable in dataset.data_vars.items():
        if name in FIELD_ALIASES[role] or variable.attrs.get("standard_name") == standards[role]:
            return name
    return None


def _time_seconds(values: np.ndarray, units: str) -> np.ndarray:
    if np.issubdtype(values.dtype, np.datetime64):
        base = values.reshape(-1)[0]
        return ((values - base) / np.timedelta64(1, "s")).astype(np.float64)
    normalized = units.lower().strip()
    factor = 1.0
    if normalized.startswith("minute"):
        factor = 60.0
    elif normalized.startswith("hour"):
        factor = 3600.0
    elif normalized.startswith("day"):
        factor = 86400.0
    elif normalized in {"1", ""}:
        raise ConversionError("dimensionless NetCDF time needs an explicit physical mapping")
    elif not normalized.startswith("second"):
        raise ConversionError(f"unsupported NetCDF time units: {units!r}")
    return np.asarray(values, dtype=np.float64) * factor


def _canonical_requested(names: Sequence[str]) -> list[str]:
    aliases = {"u": "eastward_wind", "v": "northward_wind", "w": "omega", "omega": "omega", "eastward_wind": "eastward_wind", "northward_wind": "northward_wind"}
    try:
        return list(dict.fromkeys(aliases[name] for name in names))
    except KeyError as exc:
        raise ConversionError(f"unsupported requested variable: {exc.args[0]}") from exc


def read_netcdf(
    path: Path,
    *,
    variables: Sequence[str] = ("u", "v", "omega"),
    lat_step: float = 4.0,
    lon_step: float = 4.0,
    regrid: str = "if-needed",
    vertical_velocity_mode: str = "strict",
    gravity_m_s2: float | None = None,
    time_indices: Sequence[int] | None = None,
) -> tuple[CanonicalDataset, list[PressureMapping]]:
    path = path.expanduser().resolve()
    requested = _canonical_requested(variables)
    with xr.open_dataset(path, decode_times=False, chunks={}) as dataset:
        lat_name = _coord(dataset, "latitude")
        lon_name = _coord(dataset, "longitude")
        lev_name = _coord(dataset, "level")
        time_name = _coord(dataset, "time")
        latitude = np.asarray(dataset[lat_name].values, dtype=np.float64)
        longitude = np.asarray(dataset[lon_name].values, dtype=np.float64)
        level_units = str(dataset[lev_name].attrs.get("units", ""))
        source_level = to_pa(np.asarray(dataset[lev_name].values), level_units)
        times = _time_seconds(
            np.asarray(dataset[time_name].values),
            str(dataset[time_name].attrs.get("units", "")),
        )
        if time_indices is None:
            selected_time_indices = np.arange(times.size, dtype=int)
        else:
            selected_time_indices = np.asarray(time_indices, dtype=int)
            if selected_time_indices.size == 0:
                raise ConversionError("--time-indices cannot be empty")
            if np.any(selected_time_indices < 0) or np.any(selected_time_indices >= times.size):
                raise ConversionError(
                    f"NetCDF time index outside 0..{times.size - 1}: {selected_time_indices.tolist()}"
                )
            if len(np.unique(selected_time_indices)) != selected_time_indices.size:
                raise ConversionError("duplicate NetCDF time indices")
            times = times[selected_time_indices]
        u_name = _field(dataset, "eastward_wind")
        v_name = _field(dataset, "northward_wind")
        if u_name is None or v_name is None:
            raise ConversionError("NetCDF must contain identifiable eastward and northward wind")
        selected: dict[str, np.ndarray] = {}
        for canonical, source_name in (("eastward_wind", u_name), ("northward_wind", v_name)):
            data = dataset[source_name].isel({time_name: selected_time_indices})
            missing_dims = {time_name, lev_name, lat_name, lon_name} - set(data.dims)
            if missing_dims:
                raise ConversionError(f"{source_name} lacks dimensions {sorted(missing_dims)}")
            selected[canonical] = np.asarray(
                data.transpose(time_name, lev_name, lat_name, lon_name).values,
                dtype=np.float64,
            )
        if "omega" in requested:
            omega_name = _field(dataset, "omega")
            geometric_name = _field(dataset, "geometric_w")
            density_name = _field(dataset, "density")
            native = None
            native_units = None
            geometric = None
            density = None
            if omega_name:
                native = np.asarray(dataset[omega_name].isel({time_name: selected_time_indices}).transpose(time_name, lev_name, lat_name, lon_name).values)
                native_units = str(dataset[omega_name].attrs.get("units", ""))
            if geometric_name:
                geometric = np.asarray(dataset[geometric_name].isel({time_name: selected_time_indices}).transpose(time_name, lev_name, lat_name, lon_name).values)
            if density_name:
                density = np.asarray(dataset[density_name].isel({time_name: selected_time_indices}).transpose(time_name, lev_name, lat_name, lon_name).values)
            omega, omega_method = resolve_omega(
                mode=vertical_velocity_mode,
                native_omega=native,
                native_units=native_units,
                geometric_w=geometric,
                density=density,
                gravity_m_s2=gravity_m_s2,
            )
            if omega is not None:
                selected["omega"] = omega
        else:
            omega_method = "not requested"
        global_attrs = dict(dataset.attrs)

    # Move latitude/longitude first for the common sorter/remapper.
    names = list(selected)
    latlon_fields = [selected[name].transpose(2, 3, 0, 1) for name in names]
    latitude, longitude, sorted_fields = normalize_source_grid(latitude, longitude, latlon_fields)
    target_lat, target_lon = target_regular_grid(lat_step, lon_step)
    need_regrid = not grids_equal(latitude, longitude, target_lat, target_lon)
    if regrid == "never" and need_regrid:
        raise ConversionError("NetCDF grid differs from target while --regrid never is active")
    if regrid not in {"never", "if-needed", "always"}:
        raise ConversionError(f"invalid regrid mode: {regrid}")
    mapped: dict[str, np.ndarray] = {}
    for name, values in zip(names, sorted_fields):
        if need_regrid or regrid == "always":
            mapped[name] = horizontal_remap(
                values,
                latitude,
                longitude,
                target_lat,
                target_lon,
                pole_kind="horizontal_vector" if name != "omega" else "scalar",
            )
        else:
            mapped[name] = values
    # A CF pressure coordinate is already the completed vertical stage. Integer
    # Pa labels need no safety-margin shift and must not be interpolated again.
    target_level, mapping = derive_integer_levels(source_level)
    final: dict[str, np.ndarray] = {}
    for name in requested:
        if name not in mapped:
            if name == "omega" and vertical_velocity_mode == "omit":
                continue
            raise ScientificMappingError(f"requested field {name} could not be produced")
        values = mapped[name]  # latitude, longitude, time, level
        if np.array_equal(source_level, target_level):
            converted = values
        else:
            converted = interpolate_log_pressure(values, source_level, target_level)
        final[name] = converted.transpose(2, 3, 0, 1)
    units = {name: "Pa s-1" if name == "omega" else "m s-1" for name in final}
    gravity = gravity_m_s2
    planet = PlanetParameters(
        name=str(global_attrs.get("planet", "unknown")),
        gravity_m_s2=gravity,
        source=str(path) if gravity is not None else None,
    )
    stages = [
        ProcessingStage(
            input_file=str(path),
            field=name,
            detected_grid_stage="regular_latitude_longitude",
            detected_vector_stage="CF geographic components",
            detected_vertical_stage="pressure_coordinate",
            detected_units=units[name],
            required_next_step="GRIB encoding" if not need_regrid else "target-grid adjustment and GRIB encoding",
            skipped_as_already_completed="native-grid interpolation, vector rotation, pressure derivation",
            evidence="CF coordinate/standard_name/dimension metadata",
        )
        for name in final
    ]
    return CanonicalDataset(
        time_seconds=times,
        level_pa=target_level,
        latitude=target_lat if (need_regrid or regrid == "always") else latitude,
        longitude=target_lon if (need_regrid or regrid == "always") else longitude,
        fields=final,
        units=units,
        source_files=[path],
        planet=planet,
        metadata={
            "source_kind": "netcdf",
            "omega_method": omega_method,
            "source_time_units_preserved_as_elapsed_seconds": True,
            "review_status": "pending manual review by Márkó",
        },
        stages=stages,
    ), mapping


def read_netcdf_collection(paths: Sequence[Path], **kwargs: object) -> tuple[CanonicalDataset, list[PressureMapping]]:
    if not paths:
        raise ConversionError("empty NetCDF collection")
    pairs = [read_netcdf(path, **kwargs) for path in paths]
    first, mapping = pairs[0]
    datasets = [pair[0] for pair in pairs]
    for item in datasets[1:]:
        if set(item.fields) != set(first.fields):
            raise ConversionError("NetCDF collection variables differ")
        for name, left, right in (("level", first.level_pa, item.level_pa), ("latitude", first.latitude, item.latitude), ("longitude", first.longitude, item.longitude)):
            if left.shape != right.shape or not np.allclose(left, right, atol=1e-8, rtol=0):
                raise ConversionError(f"NetCDF collection {name} coordinates differ")
    times = np.concatenate([item.time_seconds for item in datasets])
    order = np.argsort(times)
    return CanonicalDataset(
        time_seconds=times[order],
        level_pa=first.level_pa,
        latitude=first.latitude,
        longitude=first.longitude,
        fields={name: np.concatenate([item.fields[name] for item in datasets], axis=0)[order] for name in first.fields},
        units=first.units,
        source_files=[path for item in datasets for path in item.source_files],
        planet=first.planet,
        metadata={**first.metadata, "source_count": len(datasets)},
        stages=[stage for item in datasets for stage in item.stages],
    ), mapping
