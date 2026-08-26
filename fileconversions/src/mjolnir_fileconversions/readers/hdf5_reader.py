"""Reader for verified Mjolnir-processed regular-grid HDF5 products."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Sequence

import h5py
import numpy as np

from ..discovery import require_processed
from ..errors import ConversionError, ScientificMappingError
from ..models import CanonicalDataset, PlanetParameters, ProcessingStage
from ..processing.grid import horizontal_remap, normalize_source_grid, target_regular_grid
from ..processing.pressure import (
    PressureMapping,
    area_weighted_reference,
    derive_hpa_aligned_levels,
    derive_integer_levels,
    interpolate_log_pressure,
)
from ..processing.vertical_velocity import resolve_omega


PROCESSED_RE = re.compile(
    r"^(?:regrid_height_|regrid_)(?P<simulation>.+)_(?P<index>[0-9]+)\.h5$"
)


def _scalar(handle: h5py.File, name: str) -> float:
    values = np.asarray(handle[name][...]).reshape(-1)
    if values.size != 1:
        raise ConversionError(f"{handle.filename}:{name} is not scalar")
    return float(values[0])


def _roots(path: Path) -> list[Path]:
    roots = [path.parent]
    if path.parent.parent != path.parent:
        roots.append(path.parent.parent)
    return roots


def _companion(path: Path, pattern: str) -> Path | None:
    for root in _roots(path):
        matches = sorted(root.glob(pattern))
        if matches:
            return matches[0]
    return None


def read_planet_parameters(
    path: Path, simulation: str, explicit_path: Path | None = None
) -> PlanetParameters:
    planet_path = explicit_path.expanduser().resolve() if explicit_path else None
    if planet_path is not None and not planet_path.is_file():
        raise FileNotFoundError(f"explicit planet file does not exist: {planet_path}")
    if planet_path is None:
        planet_path = _companion(path, f"esp_output_planet_{simulation}.h5")
    if planet_path is None:
        planet_path = _companion(path, "esp_output_planet_*.h5")
    if planet_path is None:
        return PlanetParameters(name="unknown")
    with h5py.File(planet_path, "r") as handle:
        def optional(name: str) -> float | None:
            return _scalar(handle, name) if name in handle else None

        return PlanetParameters(
            name="Venus" if "venus" in simulation.lower() else simulation,
            radius_m=optional("A"),
            gravity_m_s2=optional("Gravit"),
            rotation_rate_s1=optional("Omega"),
            gas_constant_j_kg_k=optional("Rd"),
            heat_capacity_j_kg_k=optional("Cp"),
            reference_pressure_pa=optional("P_Ref"),
            source=str(planet_path),
        )


def read_model_time(path: Path, simulation: str, index: int) -> tuple[float, str]:
    for root in _roots(path):
        raw = root / f"esp_output_{simulation}_{index}.h5"
        if raw.is_file():
            with h5py.File(raw, "r") as handle:
                if "simulation_time" in handle:
                    return _scalar(handle, "simulation_time"), str(raw)
    raise ConversionError(
        f"No companion esp_output_{simulation}_{index}.h5 with simulation_time was found"
    )


def _choose(handle: h5py.File, names: Sequence[str], role: str) -> str:
    for name in names:
        if name in handle:
            return name
    raise ConversionError(f"Cannot identify {role}; tried {list(names)}")


def _requested(names: Sequence[str]) -> list[str]:
    aliases = {
        "u": "eastward_wind",
        "v": "northward_wind",
        "w": "omega",
        "eastward_wind": "eastward_wind",
        "northward_wind": "northward_wind",
        "omega": "omega",
        "lagrangian_tendency_of_air_pressure": "omega",
    }
    try:
        result = [aliases[name] for name in names]
    except KeyError as exc:
        raise ConversionError(f"unsupported requested variable: {exc.args[0]}") from exc
    return list(dict.fromkeys(result))


def _interpolate_if_needed(
    field: np.ndarray, source_pressure: np.ndarray, target_pressure: np.ndarray
) -> np.ndarray:
    if source_pressure.ndim == 1 and np.array_equal(source_pressure, target_pressure):
        return field.copy()
    return interpolate_log_pressure(field, source_pressure, target_pressure)


def read_processed_hdf5(
    path: Path,
    *,
    variables: Sequence[str] = ("u", "v", "omega"),
    lat_step: float = 4.0,
    lon_step: float = 4.0,
    vertical_velocity_mode: str = "strict",
    pressure_level_policy: str = "source",
    planet_file: Path | None = None,
    grid_file: Path | None = None,
) -> tuple[CanonicalDataset, list[PressureMapping]]:
    """Read one processed HDF5 file, never a native icosahedral product."""
    path = path.expanduser().resolve()
    require_processed([path])
    match = PROCESSED_RE.match(path.name)
    if not match:
        raise ConversionError(
            f"Processed input name must match regrid[_height]_<simulation>_<index>.h5: {path.name}"
        )
    simulation = match.group("simulation")
    index = int(match.group("index"))
    requested = _requested(variables)
    planet = read_planet_parameters(path, simulation, planet_file)
    elapsed, time_source = read_model_time(path, simulation, index)
    target_lat, target_lon = target_regular_grid(lat_step, lon_step)

    with h5py.File(path, "r") as handle:
        lat = np.asarray(handle["Latitude"][...], dtype=np.float64)
        lon = np.asarray(handle["Longitude"][...], dtype=np.float64)
        if grid_file is not None:
            explicit_grid = grid_file.expanduser().resolve()
            if not explicit_grid.is_file():
                raise FileNotFoundError(f"explicit grid file does not exist: {explicit_grid}")
            with h5py.File(explicit_grid, "r") as grid_handle:
                lat_key = next((name for name in ("Latitude", "latitude") if name in grid_handle), None)
                lon_key = next((name for name in ("Longitude", "longitude") if name in grid_handle), None)
                if lat_key is None or lon_key is None:
                    raise ConversionError(
                        "an explicit downstream grid file must contain independent Latitude/Longitude; "
                        "native topology files are not accepted"
                    )
                grid_lat = np.asarray(grid_handle[lat_key][...], dtype=np.float64)
                grid_lon = np.asarray(grid_handle[lon_key][...], dtype=np.float64)
            if (
                grid_lat.shape != lat.shape
                or grid_lon.shape != lon.shape
                or not np.allclose(grid_lat, lat, atol=1e-10, rtol=0)
                or not np.allclose(np.mod(grid_lon, 360.0), np.mod(lon, 360.0), atol=1e-10, rtol=0)
            ):
                raise ConversionError(
                    "explicit grid coordinates disagree with the processed HDF5; refusing double regridding"
                )
        u_name = _choose(handle, ("U", "eastward_wind", "U_mean"), "eastward wind")
        v_name = _choose(handle, ("V", "northward_wind", "V_mean"), "northward wind")
        raw_fields: dict[str, np.ndarray] = {
            "eastward_wind": np.asarray(handle[u_name][...], dtype=np.float64),
            "northward_wind": np.asarray(handle[v_name][...], dtype=np.float64),
        }
        density = np.asarray(handle["Rho"][...], dtype=np.float64) if "Rho" in handle else None
        w_name = next((name for name in ("omega", "lagrangian_tendency_of_air_pressure", "W", "W_mean") if name in handle), None)
        native_omega = None
        native_units = None
        geometric_w = None
        if w_name in {"omega", "lagrangian_tendency_of_air_pressure"}:
            native_omega = np.asarray(handle[w_name][...], dtype=np.float64)
            native_units = "Pa s-1"
        elif w_name:
            geometric_w = np.asarray(handle[w_name][...], dtype=np.float64)
        if "omega" in requested:
            omega, omega_method = resolve_omega(
                mode=vertical_velocity_mode,
                native_omega=native_omega,
                native_units=native_units,
                geometric_w=geometric_w,
                density=density,
                gravity_m_s2=planet.gravity_m_s2,
            )
            if omega is not None:
                raw_fields["omega"] = omega
        else:
            omega_method = "not requested"

        if "Pressure" in handle and handle["Pressure"].ndim == 1:
            pressure = np.asarray(handle["Pressure"][...], dtype=np.float64)
            pressure_source = "Pressure (Mjolnir pressure-grid product, Pa by upstream definition)"
            vertical_stage = "mjolnir_pressure_grid"
        elif all(name in handle for name in ("Rho", "Rd", "Temperature")):
            pressure = (
                np.asarray(handle["Rho"][...], dtype=np.float64)
                * np.asarray(handle["Rd"][...], dtype=np.float64)
                * np.asarray(handle["Temperature"][...], dtype=np.float64)
            )
            pressure_source = "derived Rho*Rd*Temperature (Pa), as in existing GRIB2 work"
            vertical_stage = "mjolnir_height_grid"
        elif "Pressure_mean" in handle:
            pressure = np.asarray(handle["Pressure_mean"][...], dtype=np.float64)
            pressure_source = "Pressure_mean (Pa by upstream definition)"
            vertical_stage = "mjolnir_height_grid_mean"
        else:
            raise ConversionError("No verified pressure coordinate can be formed")

    arrays = [raw_fields[name] for name in raw_fields]
    pressure_is_1d = pressure.ndim == 1
    sortable = arrays if pressure_is_1d else [*arrays, pressure]
    lat, lon, sorted_arrays = normalize_source_grid(lat, lon, sortable)
    if pressure_is_1d:
        raw_fields = dict(zip(raw_fields, sorted_arrays))
    else:
        raw_fields = dict(zip(raw_fields, sorted_arrays[:-1]))
        pressure = sorted_arrays[-1]

    remapped: dict[str, np.ndarray] = {}
    for name, values in raw_fields.items():
        remapped[name] = horizontal_remap(
            values,
            lat,
            lon,
            target_lat,
            target_lon,
            pole_kind="horizontal_vector" if name in {"eastward_wind", "northward_wind"} else "scalar",
        )
    if pressure_is_1d:
        remapped_pressure = pressure
        reference = pressure
        if pressure_level_policy == "hpa-aligned":
            target_pressure, mapping = derive_hpa_aligned_levels(reference)
        elif pressure_level_policy == "source":
            target_pressure, mapping = derive_integer_levels(reference)
            # Rounding a boundary outward would require extrapolation. Clamp only
            # that boundary inward; a fixed 1-D Mjolnir pgrid has no inter-column
            # variability requiring the height-grid safety margin.
            if reference[0] > reference[-1]:
                if target_pressure[0] > reference[0]:
                    target_pressure[0] = int(np.floor(reference[0]))
                if target_pressure[-1] < reference[-1]:
                    target_pressure[-1] = int(np.ceil(reference[-1]))
            else:
                if target_pressure[0] < reference[0]:
                    target_pressure[0] = int(np.ceil(reference[0]))
                if target_pressure[-1] > reference[-1]:
                    target_pressure[-1] = int(np.floor(reference[-1]))
            mapping = [
                replace(
                    item,
                    target_level_pa=int(target_pressure[index]),
                    absolute_error_pa=abs(float(target_pressure[index]) - float(reference[index])),
                    relative_error=abs(float(target_pressure[index]) - float(reference[index])) / float(reference[index]),
                    interpolation_performed=not np.isclose(target_pressure[index], reference[index], atol=1e-12, rtol=0),
                    interpolation_method="linear in log(p)" if not np.isclose(target_pressure[index], reference[index], atol=1e-12, rtol=0) else "none",
                )
                for index, item in enumerate(mapping)
            ]
        else:
            raise ConversionError(
                f"unsupported pressure-level policy: {pressure_level_policy}"
            )
    else:
        remapped_pressure = horizontal_remap(
            pressure, lat, lon, target_lat, target_lon, pole_kind="scalar"
        )
        reference = area_weighted_reference(pressure, lat)
        if pressure_level_policy == "hpa-aligned":
            target_pressure, mapping = derive_hpa_aligned_levels(
                reference, remapped_pressure
            )
        elif pressure_level_policy == "source":
            target_pressure, mapping = derive_integer_levels(
                reference, remapped_pressure
            )
        else:
            raise ConversionError(
                f"unsupported pressure-level policy: {pressure_level_policy}"
            )

    final: dict[str, np.ndarray] = {}
    units = {
        "eastward_wind": "m s-1",
        "northward_wind": "m s-1",
        "omega": "Pa s-1",
    }
    for name in requested:
        if name not in remapped:
            if name == "omega" and vertical_velocity_mode == "omit":
                continue
            raise ScientificMappingError(f"requested field {name} could not be produced")
        transformed = _interpolate_if_needed(remapped[name], remapped_pressure, target_pressure)
        final[name] = transformed.transpose(2, 0, 1)[None, ...]

    stages = [
        ProcessingStage(
            input_file=str(path),
            field=name,
            detected_grid_stage="regular_latitude_longitude_from_mjolnir",
            detected_vector_stage="geographic_u_v_already_rotated" if name != "omega" else "not_applicable",
            detected_vertical_stage=vertical_stage,
            detected_units=units[name],
            required_next_step=(
                "target-grid adjustment, log-pressure interpolation to exact integer-hPa surfaces, GRIB encoding"
                if pressure_level_policy == "hpa-aligned"
                else "target-grid adjustment, integer-Pa normalization, GRIB encoding"
            ),
            skipped_as_already_completed="native-grid interpolation and vector rotation",
            evidence=(
                "Latitude/Longitude plus U/V structure; origin/mjolnir_advance:mjolnir/hamarr.py "
                "regrid() computes geographic U/V before writing"
            ),
        )
        for name in final
    ]
    dataset = CanonicalDataset(
        time_seconds=np.array([elapsed]),
        level_pa=target_pressure,
        latitude=target_lat,
        longitude=target_lon,
        fields=final,
        units={name: units[name] for name in final},
        source_files=[path],
        planet=planet,
        metadata={
            "simulation_name": simulation,
            "source_index": index,
            "source_kind": "mjolnir_processed",
            "source_grid": f"regular lat-lon {lat.size}x{lon.size}",
            "target_grid": f"regular lat-lon {target_lat.size}x{target_lon.size}",
            "pressure_source": pressure_source,
            "pressure_level_policy": pressure_level_policy,
            "vertical_interpolation_method": (
                "piecewise linear in log(p)" if any(
                    item.interpolation_performed for item in mapping
                ) else "none"
            ),
            "vertical_interpolation_count": int(
                any(item.interpolation_performed for item in mapping)
            ),
            "omega_method": omega_method,
            "time_source": time_source,
            "explicit_grid_file": str(grid_file.expanduser().resolve()) if grid_file else None,
            "time_reference": "elapsed model seconds; GRIB uses configurable technical epoch",
            "review_status": "pending manual review by Márkó",
        },
        stages=stages,
    )
    return dataset, mapping


def read_processed_hdf5_collection(
    paths: Sequence[Path], **kwargs: object
) -> tuple[CanonicalDataset, list[PressureMapping]]:
    if not paths:
        raise ConversionError("empty HDF5 collection")
    datasets: list[CanonicalDataset] = []
    mapping: list[PressureMapping] = []
    for path in paths:
        dataset, local_mapping = read_processed_hdf5(path, **kwargs)
        datasets.append(dataset)
        if not mapping:
            mapping = local_mapping
    first = datasets[0]
    for item in datasets[1:]:
        for name, left, right in (
            ("level", first.level_pa, item.level_pa),
            ("latitude", first.latitude, item.latitude),
            ("longitude", first.longitude, item.longitude),
        ):
            if left.shape != right.shape or not np.allclose(left, right, atol=1e-8, rtol=0):
                raise ConversionError(f"multi-file {name} coordinates differ")
        if set(item.fields) != set(first.fields):
            raise ConversionError("multi-file canonical variables differ")
    order = np.argsort([item.time_seconds[0] for item in datasets])
    datasets = [datasets[index] for index in order]
    return CanonicalDataset(
        time_seconds=np.concatenate([item.time_seconds for item in datasets]),
        level_pa=first.level_pa,
        latitude=first.latitude,
        longitude=first.longitude,
        fields={name: np.concatenate([item.fields[name] for item in datasets], axis=0) for name in first.fields},
        units=first.units,
        source_files=[path for item in datasets for path in item.source_files],
        planet=first.planet,
        metadata={**first.metadata, "source_count": len(datasets)},
        stages=[stage for item in datasets for stage in item.stages],
    ), mapping
