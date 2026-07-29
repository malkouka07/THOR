#!/usr/bin/env python3
"""Convert THOR/MJOLNIR regridded HDF5 output to RePLaT-ready NetCDF4.

The raw ``esp_output_*.h5`` files use THOR's native icosahedral grid.  This
program deliberately consumes the matching ``regrid_height_*.h5`` products,
which MJOLNIR has already put on a regular latitude/longitude grid.  It then:

* remaps the 4-degree cell-centre grid to a regular grid containing both poles;
* derives one common, integer-Pa pressure coordinate;
* interpolates every column linearly in log(p);
* writes collocated winds in CF-style ``(time, level, latitude, longitude)``
  order.

No source file is ever opened in write mode.  Existing outputs are protected
unless ``--overwrite`` is explicitly supplied.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import h5py
import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator


CF_CONVENTIONS = "CF-1.10"
HEIGHT_FILE_RE = re.compile(
    r"^regrid_height_(?P<simulation>.+)_(?P<index>[0-9]+)\.h5$"
)


@dataclass(frozen=True)
class InputRecord:
    path: Path
    simulation_id: str
    index: int
    raw_path: Path
    time_seconds: float
    time_source: str


@dataclass(frozen=True)
class VariableChoice:
    source_name: str
    output_name: str
    standard_name: str
    long_name: str
    units: str
    pole_kind: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert THOR MJOLNIR regrid_height HDF5 files to CF-style, "
            "integer-pressure RePLaT NetCDF4 files."
        )
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--test-mode",
        action="store_true",
        help="Convert one representative file (or --test-index).",
    )
    mode.add_argument(
        "--all-files",
        action="store_true",
        help="Convert every discovered regrid_height file.",
    )
    parser.add_argument(
        "--test-index",
        type=int,
        help="Specific output index for --test-mode; otherwise the median file is used.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        help="Optional safety limit, useful for a small multi-file trial.",
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        action="append",
        help="Explicit regrid_height HDF5 input; may be supplied repeatedly.",
    )
    parser.add_argument("--u-var", help="Override the detected zonal-wind variable.")
    parser.add_argument("--v-var", help="Override the detected meridional-wind variable.")
    parser.add_argument(
        "--vertical-var", help="Override the detected vertical-velocity variable."
    )
    parser.add_argument(
        "--pressure-var", help="Override the detected 3-D pressure variable."
    )
    parser.add_argument(
        "--vertical-kind",
        choices=("auto", "geometric", "omega"),
        default="auto",
        help="Physical type of the vertical variable. No w/omega conversion is done.",
    )
    parser.add_argument(
        "--latitude-step",
        type=float,
        default=4.0,
        help="Target latitude spacing in degrees; must divide 180 exactly.",
    )
    parser.add_argument(
        "--longitude-step",
        type=float,
        default=4.0,
        help="Target longitude spacing in degrees; must divide 360 exactly.",
    )
    parser.add_argument(
        "--vector-pole-method",
        choices=("zero", "ring-mean-components"),
        default="zero",
        help=(
            "Exact-pole treatment for U/V. 'zero' imposes vector regularity; "
            "'ring-mean-components' repeats the nearest-ring component means."
        ),
    )
    parser.add_argument(
        "--pressure-levels-file",
        type=Path,
        help=(
            "CSV from a previous run or one-column text file containing a common "
            "integer-Pa target grid. Recommended for --all-files."
        ),
    )
    parser.add_argument(
        "--pressure-boundary-policy",
        choices=("safe", "rounded"),
        default="safe",
        help=(
            "'safe' moves only the top/bottom target levels inside every column "
            "of the reference file; 'rounded' uses nearest-integer reference levels "
            "and fails if extrapolation would be needed."
        ),
    )
    parser.add_argument(
        "--allow-index-time",
        action="store_true",
        help=(
            "If matching raw files are absent, use the output index as a numeric "
            "time coordinate. This is off by default because it loses physical time."
        ),
    )
    parser.add_argument(
        "--time-step-seconds",
        type=float,
        help=(
            "Explicit output cadence used to reconstruct missing simulation_time as "
            "(index - --time-index-offset) * cadence. Use only when verified from "
            "the THOR configuration and surviving raw files."
        ),
    )
    parser.add_argument(
        "--time-index-offset",
        type=float,
        default=1.0,
        help="Index offset for --time-step-seconds (default: 1).",
    )
    parser.add_argument(
        "--pressure-boundary-margin-pa",
        type=float,
        default=1.0,
        help=(
            "Additional inward safety margin at the bottom/top pressure bounds "
            "when --pressure-boundary-policy=safe (default: 1 Pa)."
        ),
    )
    parser.add_argument(
        "--compression-level", type=int, default=4, choices=range(0, 10)
    )
    existing = parser.add_mutually_exclusive_group()
    existing.add_argument("--overwrite", action="store_true")
    existing.add_argument(
        "--skip-existing",
        action="store_true",
        help="Leave existing standardized outputs unchanged and continue.",
    )
    parser.add_argument(
        "--strict-time",
        action="store_true",
        help="Treat irregular multi-file time spacing as an error instead of a warning.",
    )
    return parser.parse_args()


def setup_logging(output_dir: Path) -> logging.Logger:
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("thor_replat")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    file_handler = logging.FileHandler(log_dir / "conversion.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(stream)
    logger.addHandler(file_handler)
    return logger


def require_output_tree(output_dir: Path) -> None:
    for name in ("standard_netcdf", "grib2", "logs", "scripts", "validation"):
        (output_dir / name).mkdir(parents=True, exist_ok=True)


def scalar(dataset: h5py.Dataset) -> float:
    value = np.asarray(dataset[...]).reshape(-1)
    if value.size != 1:
        raise ValueError(f"{dataset.name} is not scalar: shape={dataset.shape}")
    return float(value[0])


def read_time(
    raw_path: Path,
    index: int,
    allow_index: bool,
    time_step_seconds: float | None,
    time_index_offset: float,
) -> tuple[float, str]:
    if raw_path.is_file():
        with h5py.File(raw_path, "r") as handle:
            if "simulation_time" not in handle:
                raise ValueError(f"Missing simulation_time in {raw_path}")
            return scalar(handle["simulation_time"]), "raw simulation_time"
    if time_step_seconds is not None:
        if time_step_seconds <= 0:
            raise ValueError("--time-step-seconds must be positive")
        return (
            float((index - time_index_offset) * time_step_seconds),
            "index reconstructed with explicit cadence",
        )
    if allow_index:
        return float(index), "output index (not physical time)"
    raise FileNotFoundError(
        f"Matching raw file not found: {raw_path}. Supply a verified "
        "--time-step-seconds value or use --allow-index-time only if an "
        "output-index coordinate is acceptable."
    )


def record_from_path(path: Path, args: argparse.Namespace) -> InputRecord:
    match = HEIGHT_FILE_RE.match(path.name)
    if not match:
        raise ValueError(
            f"Unsupported input name {path.name!r}; expected "
            "regrid_height_<simulation>_<integer>.h5"
        )
    simulation = match.group("simulation")
    index = int(match.group("index"))
    raw = path.parent / f"esp_output_{simulation}_{index}.h5"
    time_seconds, time_source = read_time(
        raw,
        index,
        args.allow_index_time,
        args.time_step_seconds,
        args.time_index_offset,
    )
    return InputRecord(
        path=path,
        simulation_id=simulation,
        index=index,
        raw_path=raw,
        time_seconds=time_seconds,
        time_source=time_source,
    )


def discover_records(args: argparse.Namespace, logger: logging.Logger) -> list[InputRecord]:
    if args.input_file:
        candidates = [p.expanduser().resolve() for p in args.input_file]
    else:
        candidates = sorted(
            args.input_dir.glob("regrid_height_*_[0-9]*.h5"),
            key=lambda p: int(HEIGHT_FILE_RE.match(p.name).group("index"))
            if HEIGHT_FILE_RE.match(p.name)
            else math.inf,
        )
    candidates = [p for p in candidates if HEIGHT_FILE_RE.match(p.name)]
    if not candidates:
        raise FileNotFoundError(
            f"No regrid_height_<simulation>_<index>.h5 files in {args.input_dir}"
        )
    if args.test_mode:
        if args.test_index is not None:
            selected = [
                p
                for p in candidates
                if int(HEIGHT_FILE_RE.match(p.name).group("index")) == args.test_index
            ]
            if not selected:
                raise FileNotFoundError(
                    f"No regrid_height input with index {args.test_index}"
                )
            candidates = [selected[0]]
        else:
            candidates = [candidates[len(candidates) // 2]]
    if args.max_files is not None:
        if args.max_files < 1:
            raise ValueError("--max-files must be positive")
        candidates = candidates[: args.max_files]
    records = [record_from_path(p, args) for p in candidates]
    records.sort(key=lambda item: (item.time_seconds, item.index))
    simulations = {record.simulation_id for record in records}
    if len(simulations) != 1:
        raise ValueError(f"Inputs contain multiple simulation IDs: {simulations}")
    logger.info(
        "Selected %d input(s), index %d..%d",
        len(records),
        min(record.index for record in records),
        max(record.index for record in records),
    )
    return records


def check_times(
    records: Sequence[InputRecord], strict: bool, logger: logging.Logger
) -> None:
    times = np.array([record.time_seconds for record in records], dtype=np.float64)
    if not np.all(np.isfinite(times)):
        raise ValueError("Non-finite input time found")
    if len(np.unique(times)) != len(times):
        raise ValueError("Duplicate simulation_time values found")
    if len(times) > 1 and not np.all(np.diff(times) > 0):
        raise ValueError("Input times are not strictly increasing")
    if len(times) < 3:
        logger.info("Time continuity: fewer than three selected points; cadence not inferred")
        return
    diffs = np.diff(times)
    cadence = float(np.median(diffs))
    irregular = np.where(~np.isclose(diffs, cadence, rtol=1e-9, atol=1e-6))[0]
    if irregular.size:
        message = (
            f"Time continuity: {irregular.size} gap(s) differ from median cadence "
            f"{cadence:g} s"
        )
        if strict:
            raise ValueError(message)
        logger.warning(message)
    else:
        logger.info("Time continuity: uniform cadence %.12g s", cadence)


def decode_attr(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray) and value.size == 1:
        return decode_attr(value.reshape(-1)[0])
    return str(value)


def dataset_units(dataset: h5py.Dataset) -> str | None:
    for key in ("units", "Units", "unit"):
        if key in dataset.attrs:
            return decode_attr(dataset.attrs[key]).strip()
    return None


def pick_name(
    handle: h5py.File,
    override: str | None,
    candidates: Sequence[str],
    role: str,
) -> str:
    if override:
        if override not in handle:
            raise KeyError(f"Requested {role} variable {override!r} is absent")
        return override
    exact = [name for name in candidates if name in handle]
    if exact:
        return exact[0]
    lowered = {name.lower(): name for name in handle.keys()}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    raise KeyError(
        f"Could not identify {role}; candidates={list(candidates)}, "
        f"available={list(handle.keys())}"
    )


def identify_variables(
    handle: h5py.File, args: argparse.Namespace
) -> tuple[VariableChoice, VariableChoice, VariableChoice, str]:
    u_name = pick_name(
        handle,
        args.u_var,
        ("U", "u", "eastward_wind", "zonal_wind", "U_mean"),
        "zonal wind",
    )
    v_name = pick_name(
        handle,
        args.v_var,
        ("V", "v", "northward_wind", "meridional_wind", "V_mean"),
        "meridional wind",
    )
    z_name = pick_name(
        handle,
        args.vertical_var,
        (
            "W",
            "w",
            "omega",
            "vertical_velocity",
            "upward_air_velocity",
            "lagrangian_tendency_of_air_pressure",
            "W_mean",
        ),
        "vertical velocity",
    )
    mean_winds = all(name.endswith("_mean") for name in (u_name, v_name, z_name))
    if args.pressure_var:
        pressure_name = pick_name(
            handle, args.pressure_var, (), "pressure"
        )
    elif (
        not mean_winds
        and all(name in handle for name in ("Rho", "Rd", "Temperature"))
        and handle["Rho"].shape == handle[u_name].shape
        and handle["Rd"].shape == handle[u_name].shape
        and handle["Temperature"].shape == handle[u_name].shape
    ):
        # MJOLNIR omits instantaneous Pressure from regrid_height files, but its
        # saved Temperature was calculated as Pressure/(Rd*Rho).  Reconstructing
        # Rho*Rd*Temperature therefore keeps instantaneous winds on an
        # instantaneous pressure coordinate.  Pressure_mean is reserved for the
        # *_mean wind fields.
        pressure_name = "derived:Rho*Rd*Temperature"
    else:
        pressure_name = pick_name(
            handle,
            None,
            ("Pressure_mean", "Pressure", "pressure", "air_pressure"),
            "pressure",
        )

    for name, role in ((u_name, "U"), (v_name, "V"), (z_name, "vertical velocity")):
        if handle[name].ndim != 3:
            raise ValueError(f"{role} {name} must be 3-D, got {handle[name].shape}")

    uv_units = dataset_units(handle[u_name]) or dataset_units(handle[v_name])
    if uv_units is None and (u_name, v_name) in {
        ("U", "V"),
        ("U_mean", "V_mean"),
    }:
        # MJOLNIR derives these from horizontal momentum / density.
        uv_units = "m s-1"
    if not uv_units or uv_units.replace(" ", "") not in {
        "ms-1",
        "m/s",
        "ms^-1",
        "ms**-1",
    }:
        raise ValueError(
            f"Cannot verify U/V as velocity in m/s (detected units={uv_units!r})"
        )

    vertical_units = dataset_units(handle[z_name])
    kind = args.vertical_kind
    if kind == "auto":
        normalized = (vertical_units or "").replace(" ", "").lower()
        if "pa" in normalized and ("/s" in normalized or "s-1" in normalized):
            kind = "omega"
        elif normalized in {"m/s", "ms-1", "ms^-1", "ms**-1"}:
            kind = "geometric"
        elif z_name in {
            "W",
            "w",
            "W_mean",
            "upward_air_velocity",
            "vertical_velocity",
        }:
            # For MJOLNIR regrid_height products, W = interface Wh interpolated
            # to layer centres and divided by Rho, hence geometrical m/s.
            kind = "geometric"
            vertical_units = "m s-1"
        elif z_name in {"omega", "lagrangian_tendency_of_air_pressure"}:
            kind = "omega"
            vertical_units = "Pa s-1"
        else:
            raise ValueError(
                f"Cannot infer physical type of {z_name!r}; use --vertical-kind"
            )

    if kind == "geometric":
        z_choice = VariableChoice(
            z_name,
            "upward_air_velocity",
            "upward_air_velocity",
            "Upward air velocity",
            vertical_units or "m s-1",
            "scalar",
        )
    else:
        z_choice = VariableChoice(
            z_name,
            "lagrangian_tendency_of_air_pressure",
            "lagrangian_tendency_of_air_pressure",
            "Lagrangian tendency of air pressure",
            vertical_units or "Pa s-1",
            "scalar",
        )

    return (
        VariableChoice(
            u_name,
            "eastward_wind",
            "eastward_wind",
            "Eastward wind",
            "m s-1",
            "vector",
        ),
        VariableChoice(
            v_name,
            "northward_wind",
            "northward_wind",
            "Northward wind",
            "m s-1",
            "vector",
        ),
        z_choice,
        pressure_name,
    )


def target_coordinates(
    latitude_step: float, longitude_step: float
) -> tuple[np.ndarray, np.ndarray]:
    nlat_intervals = round(180.0 / latitude_step)
    nlon = round(360.0 / longitude_step)
    if not math.isclose(nlat_intervals * latitude_step, 180.0, abs_tol=1e-10):
        raise ValueError("--latitude-step must divide 180 degrees exactly")
    if not math.isclose(nlon * longitude_step, 360.0, abs_tol=1e-10):
        raise ValueError("--longitude-step must divide 360 degrees exactly")
    latitude = np.linspace(-90.0, 90.0, nlat_intervals + 1, dtype=np.float64)
    longitude = np.arange(nlon, dtype=np.float64) * (360.0 / nlon)
    latitude[0], latitude[-1] = -90.0, 90.0
    longitude[0] = 0.0
    return latitude, longitude


def validate_source_grid(
    latitude: np.ndarray,
    longitude: np.ndarray,
    arrays: Sequence[np.ndarray],
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    latitude = np.asarray(latitude, dtype=np.float64)
    longitude = np.mod(np.asarray(longitude, dtype=np.float64), 360.0)
    lat_order = np.argsort(latitude)
    lon_order = np.argsort(longitude)
    latitude = latitude[lat_order]
    longitude = longitude[lon_order]
    if len(np.unique(latitude)) != len(latitude):
        raise ValueError("Duplicate source latitudes")
    if len(np.unique(longitude)) != len(longitude):
        raise ValueError("Duplicate source longitudes after 0..360 normalization")
    if not np.all(np.diff(latitude) > 0) or not np.all(np.diff(longitude) > 0):
        raise ValueError("Source latitude/longitude must be strictly increasing")
    sorted_arrays: list[np.ndarray] = []
    for array in arrays:
        array = np.asarray(array, dtype=np.float64)
        if array.shape[:2] != (len(lat_order), len(lon_order)):
            raise ValueError(
                f"Field shape {array.shape} does not match "
                f"lat/lon {(len(lat_order), len(lon_order))}"
            )
        sorted_arrays.append(array[lat_order][:, lon_order])
    return latitude, longitude, sorted_arrays


def horizontal_remap(
    field: np.ndarray,
    src_lat: np.ndarray,
    src_lon: np.ndarray,
    target_lat: np.ndarray,
    target_lon: np.ndarray,
    pole_kind: str,
    vector_pole_method: str,
) -> np.ndarray:
    """Bilinearly remap the interior and explicitly construct both poles."""
    lon_ext = np.concatenate(([src_lon[-1] - 360.0], src_lon, [src_lon[0] + 360.0]))
    field_ext = np.concatenate((field[:, -1:, :], field, field[:, :1, :]), axis=1)
    interpolator = RegularGridInterpolator(
        (src_lat, lon_ext),
        field_ext,
        method="linear",
        bounds_error=True,
    )
    interior_lat = target_lat[1:-1]
    lat_mesh, lon_mesh = np.meshgrid(interior_lat, target_lon, indexing="ij")
    points = np.column_stack((lat_mesh.ravel(), lon_mesh.ravel()))
    interior = interpolator(points).reshape(
        len(interior_lat), len(target_lon), field.shape[2]
    )
    result = np.empty(
        (len(target_lat), len(target_lon), field.shape[2]), dtype=np.float64
    )
    result[1:-1] = interior
    if pole_kind == "vector" and vector_pole_method == "zero":
        result[0] = 0.0
        result[-1] = 0.0
    else:
        result[0] = np.mean(field[0], axis=0)[None, :]
        result[-1] = np.mean(field[-1], axis=0)[None, :]
    return result


def area_weighted_reference_pressure(
    pressure: np.ndarray, latitude: np.ndarray
) -> np.ndarray:
    weights = np.cos(np.deg2rad(latitude))[:, None, None]
    weights = np.broadcast_to(weights, pressure.shape)
    finite = np.isfinite(pressure)
    numerator = np.sum(np.where(finite, pressure * weights, 0.0), axis=(0, 1))
    denominator = np.sum(np.where(finite, weights, 0.0), axis=(0, 1))
    if np.any(denominator == 0):
        raise ValueError("A pressure level has no finite values")
    return numerator / denominator


def levels_from_file(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            raise ValueError(f"No rows in {path}")
        candidate_columns = (
            "target_integer_pa",
            "target integer Pa level",
            "target_pa",
            "level",
        )
        column = next(
            (name for name in candidate_columns if name in rows[0]), None
        )
        if column is None:
            raise ValueError(
                f"Cannot find a target-pressure column in {path}; "
                f"columns={list(rows[0])}"
            )
        levels = np.array([int(round(float(row[column]))) for row in rows], dtype=np.int64)
    else:
        raw = np.loadtxt(path, ndmin=1)
        if raw.ndim == 2:
            raw = raw[:, -1]
        levels = np.rint(raw).astype(np.int64)
    if np.any(levels <= 0) or not np.all(np.diff(levels) < 0):
        raise ValueError("Pressure levels must be positive and strictly decreasing")
    if len(np.unique(levels)) != len(levels):
        raise ValueError("Pressure levels are not unique")
    return levels


def derive_pressure_levels(
    reference: np.ndarray,
    remapped_pressure: np.ndarray,
    policy: str,
    boundary_margin_pa: float,
) -> tuple[np.ndarray, np.ndarray]:
    if np.any(reference <= 0) or not np.all(np.diff(reference) < 0):
        raise ValueError("Reference pressure is not positive and surface-to-top monotonic")
    target = np.rint(reference).astype(np.int64)
    if len(np.unique(target)) != len(target):
        raise ValueError("Rounding collapses two pressure levels to the same integer Pa")
    column_max = remapped_pressure[:, :, 0]
    column_min = remapped_pressure[:, :, -1]
    if boundary_margin_pa < 0:
        raise ValueError("--pressure-boundary-margin-pa cannot be negative")
    safe_high = int(
        math.floor(float(np.nanmin(column_max)) - boundary_margin_pa)
    )
    safe_low = int(
        math.ceil(float(np.nanmax(column_min)) + boundary_margin_pa)
    )
    if policy == "safe":
        target[0] = min(target[0], safe_high)
        target[-1] = max(target[-1], safe_low)
    if not np.all(np.diff(target) < 0):
        raise ValueError(f"Derived target pressure is not strictly decreasing: {target}")
    return target, np.array([safe_high, safe_low], dtype=np.int64)


def write_pressure_mapping(
    path: Path,
    reference: np.ndarray,
    target: np.ndarray,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            (
                "original_level",
                "original_unit",
                "original_level_pa",
                "target_integer_pa",
                "absolute_difference_pa",
                "relative_difference",
                "interpolated",
            )
        )
        for index, (source, destination) in enumerate(zip(reference, target)):
            writer.writerow(
                (
                    index,
                    "Pa",
                    f"{source:.12g}",
                    int(destination),
                    f"{abs(destination - source):.12g}",
                    f"{abs(destination - source) / source:.12g}",
                    "yes",
                )
            )


def interpolate_log_pressure(
    field: np.ndarray,
    pressure: np.ndarray,
    target_pressure: np.ndarray,
) -> tuple[np.ndarray, int]:
    if field.shape != pressure.shape:
        raise ValueError(
            f"Field/pressure shape mismatch: {field.shape} versus {pressure.shape}"
        )
    if np.any(~np.isfinite(field)) or np.any(~np.isfinite(pressure)):
        raise ValueError("Input field or pressure contains NaN/Inf")
    if np.any(pressure <= 0):
        raise ValueError("Pressure must be positive for log(p) interpolation")
    if np.any(np.diff(pressure, axis=2) >= 0):
        raise ValueError("Pressure is not strictly decreasing with height in every column")

    log_target = np.log(target_pressure.astype(np.float64))
    output = np.empty(
        (field.shape[0], field.shape[1], len(target_pressure)), dtype=np.float64
    )
    out_of_range = 0
    tolerance = 1e-10
    for ilat in range(field.shape[0]):
        for ilon in range(field.shape[1]):
            p_column = pressure[ilat, ilon]
            if (
                target_pressure[0] > p_column[0] + tolerance
                or target_pressure[-1] < p_column[-1] - tolerance
            ):
                out_of_range += 1
                continue
            output[ilat, ilon] = np.interp(
                log_target[::-1],
                np.log(p_column[::-1]),
                field[ilat, ilon, ::-1],
            )[::-1]
    if out_of_range:
        raise ValueError(
            f"{out_of_range} columns would require vertical extrapolation. "
            "Use a pressure grid inside all column bounds."
        )
    return output, out_of_range


def stats(array: np.ndarray, latitude: np.ndarray | None = None) -> dict[str, float]:
    array = np.asarray(array, dtype=np.float64)
    finite = np.isfinite(array)
    result = {
        "finite_count": int(np.count_nonzero(finite)),
        "total_count": int(array.size),
        "min": float(np.nanmin(array)),
        "max": float(np.nanmax(array)),
        "mean": float(np.nanmean(array)),
        "std": float(np.nanstd(array)),
    }
    if latitude is not None:
        weights = np.cos(np.deg2rad(latitude))[:, None, None]
        weights = np.broadcast_to(weights, array.shape)
        valid_weights = np.where(finite, weights, 0.0)
        result["area_weighted_mean"] = float(
            np.sum(np.where(finite, array * weights, 0.0)) / np.sum(valid_weights)
        )
    return result


def netcdf_encoding(
    dataset: xr.Dataset, compression_level: int
) -> dict[str, dict[str, Any]]:
    encoding: dict[str, dict[str, Any]] = {}
    for name, data in dataset.data_vars.items():
        if data.ndim == 4:
            encoding[name] = {
                "dtype": "float32",
                "zlib": compression_level > 0,
                "complevel": compression_level,
                "shuffle": True,
                "_FillValue": np.float32(9.96921e36),
                "chunksizes": (
                    1,
                    min(10, data.sizes["level"]),
                    min(46, data.sizes["latitude"]),
                    min(90, data.sizes["longitude"]),
                ),
            }
    encoding["time"] = {"dtype": "float64", "_FillValue": None}
    encoding["level"] = {"dtype": "int32", "_FillValue": None}
    encoding["latitude"] = {"dtype": "float64", "_FillValue": None}
    encoding["longitude"] = {"dtype": "float64", "_FillValue": None}
    return encoding


def convert_one(
    record: InputRecord,
    args: argparse.Namespace,
    target_lat: np.ndarray,
    target_lon: np.ndarray,
    target_pressure: np.ndarray | None,
    reference_pressure: np.ndarray | None,
    logger: logging.Logger,
) -> tuple[Path, np.ndarray, np.ndarray, dict[str, Any]]:
    logger.info("Reading %s", record.path)
    with h5py.File(record.path, "r") as handle:
        u_choice, v_choice, z_choice, pressure_name = identify_variables(handle, args)
        choices = (u_choice, v_choice, z_choice)
        src_lat = np.asarray(handle["Latitude"][...], dtype=np.float64)
        src_lon = np.asarray(handle["Longitude"][...], dtype=np.float64)
        arrays = [
            np.asarray(handle[choice.source_name][...], dtype=np.float64)
            for choice in choices
        ]
        if pressure_name == "derived:Rho*Rd*Temperature":
            pressure = (
                np.asarray(handle["Rho"][...], dtype=np.float64)
                * np.asarray(handle["Rd"][...], dtype=np.float64)
                * np.asarray(handle["Temperature"][...], dtype=np.float64)
            )
        else:
            pressure = np.asarray(handle[pressure_name][...], dtype=np.float64)
    src_lat, src_lon, sorted_fields = validate_source_grid(
        src_lat, src_lon, [*arrays, pressure]
    )
    arrays, pressure = sorted_fields[:-1], sorted_fields[-1]
    if pressure.shape != arrays[0].shape:
        raise ValueError(
            f"Pressure {pressure_name} shape {pressure.shape} differs from winds "
            f"{arrays[0].shape}; staggered or incompatible input is not supported"
        )
    pressure_units = (
        "Pa"
        if pressure_name == "derived:Rho*Rd*Temperature"
        else dataset_pressure_units(record.path, pressure_name)
    )
    if pressure_units not in (None, "Pa", "pascal"):
        raise ValueError(
            f"Pressure units are not Pa: {pressure_units!r}"
        )

    remapped_pressure = horizontal_remap(
        pressure,
        src_lat,
        src_lon,
        target_lat,
        target_lon,
        pole_kind="scalar",
        vector_pole_method=args.vector_pole_method,
    )
    remapped_fields = [
        horizontal_remap(
            array,
            src_lat,
            src_lon,
            target_lat,
            target_lon,
            pole_kind=choice.pole_kind,
            vector_pole_method=args.vector_pole_method,
        )
        for choice, array in zip(choices, arrays)
    ]

    local_reference = area_weighted_reference_pressure(pressure, src_lat)
    if reference_pressure is None:
        reference_pressure = local_reference
    if target_pressure is None:
        target_pressure, safe_bounds = derive_pressure_levels(
            reference_pressure,
            remapped_pressure,
            args.pressure_boundary_policy,
            args.pressure_boundary_margin_pa,
        )
        logger.info(
            "Pressure grid derived from index %d; no-extrapolation bounds %d..%d Pa",
            record.index,
            safe_bounds[1],
            safe_bounds[0],
        )

    final_fields: list[np.ndarray] = []
    variable_stats: dict[str, Any] = {}
    for choice, source_field, horizontal_field in zip(
        choices, arrays, remapped_fields
    ):
        final, _ = interpolate_log_pressure(
            horizontal_field, remapped_pressure, target_pressure
        )
        final_fields.append(final)
        variable_stats[choice.output_name] = {
            "source_height_grid": stats(source_field, src_lat),
            "horizontal_height_grid": stats(horizontal_field, target_lat),
            "output_pressure_grid": stats(final, target_lat),
        }

    time_units = (
        "1"
        if record.time_source == "output index (not physical time)"
        else "seconds since 0001-01-01 00:00:00"
    )
    time_attrs: dict[str, Any] = {
        "standard_name": "time",
        "long_name": (
            "THOR output index"
            if time_units == "1"
            else "Time elapsed since THOR simulation origin"
        ),
        "units": time_units,
        "axis": "T",
    }
    if time_units != "1":
        time_attrs["calendar"] = "none"

    data_vars: dict[str, xr.DataArray] = {}
    for choice, data in zip(choices, final_fields):
        data_vars[choice.output_name] = xr.DataArray(
            data.transpose(2, 0, 1)[None, ...],
            dims=("time", "level", "latitude", "longitude"),
            attrs={
                "standard_name": choice.standard_name,
                "long_name": choice.long_name,
                "units": choice.units,
                "original_variable_name": choice.source_name,
                "horizontal_interpolation": "periodic bilinear latitude-longitude",
                "vertical_interpolation": "linear in log(pressure)",
                "pole_treatment": (
                    "nearest source latitude-ring zonal mean, repeated at all longitudes"
                    if choice.pole_kind == "scalar"
                    else (
                        "both horizontal components set to zero at exact poles "
                        "to impose vector-field regularity"
                        if args.vector_pole_method == "zero"
                        else "nearest source latitude-ring component means, repeated"
                    )
                ),
            },
        )

    dataset = xr.Dataset(
        data_vars=data_vars,
        coords={
            "time": xr.DataArray(
                np.array([record.time_seconds], dtype=np.float64),
                dims=("time",),
                attrs=time_attrs,
            ),
            "level": xr.DataArray(
                target_pressure.astype(np.int32),
                dims=("level",),
                attrs={
                    "standard_name": "air_pressure",
                    "long_name": "Pressure level",
                    "units": "Pa",
                    "positive": "down",
                    "axis": "Z",
                },
            ),
            "latitude": xr.DataArray(
                target_lat,
                dims=("latitude",),
                attrs={
                    "standard_name": "latitude",
                    "long_name": "Latitude",
                    "units": "degrees_north",
                    "axis": "Y",
                },
            ),
            "longitude": xr.DataArray(
                target_lon,
                dims=("longitude",),
                attrs={
                    "standard_name": "longitude",
                    "long_name": "Longitude",
                    "units": "degrees_east",
                    "axis": "X",
                    "modulo": 360.0,
                },
            ),
        },
        attrs={
            "Conventions": CF_CONVENTIONS,
            "title": "THOR winds prepared for RePLaT",
            "institution": "Generated from THOR/MJOLNIR output",
            "source": "THOR native grid followed by MJOLNIR height regridding",
            "history": (
                "Converted by convert_thor_to_replat.py; horizontal bilinear "
                "interpolation without polar extrapolation; vertical log(p) interpolation"
            ),
            "simulation_id": record.simulation_id,
            "source_file": record.path.name,
            "source_raw_file": record.raw_path.name,
            "source_output_index": record.index,
            "time_source": record.time_source,
            "source_pressure_variable": pressure_name,
            "source_grid": (
                f"regular lat-lon, {len(src_lat)}x{len(src_lon)}, "
                f"lat {src_lat[0]:g}..{src_lat[-1]:g}, "
                f"lon {src_lon[0]:g}..{src_lon[-1]:g}"
            ),
            "target_grid": (
                f"regular lat-lon including poles, {len(target_lat)}x{len(target_lon)}"
            ),
            "pressure_level_order": "surface_to_top",
            "pressure_reference": (
                "cos(latitude)-weighted horizontal mean of the selected source "
                "pressure at each height level"
            ),
            "vertical_velocity_conversion": "none",
            "vector_pole_method": args.vector_pole_method,
        },
    )
    output_path = (
        args.output_dir
        / "standard_netcdf"
        / f"replat_{record.simulation_id}_{record.index:08d}.nc"
    )
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(
            f"Refusing to overwrite {output_path}; use --overwrite explicitly"
        )
    temporary = output_path.with_suffix(output_path.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    logger.info("Writing %s", output_path)
    try:
        dataset.to_netcdf(
            temporary,
            engine="netcdf4",
            format="NETCDF4",
            encoding=netcdf_encoding(dataset, args.compression_level),
            unlimited_dims=("time",),
        )
        temporary.replace(output_path)
    finally:
        dataset.close()
        if temporary.exists():
            temporary.unlink()

    manifest = {
        "source": str(record.path),
        "raw_source": str(record.raw_path),
        "output": str(output_path),
        "index": record.index,
        "time_seconds": record.time_seconds,
        "time_source": record.time_source,
        "variables": {
            choice.output_name: {
                "source_name": choice.source_name,
                "units": choice.units,
                **variable_stats[choice.output_name],
            }
            for choice in choices
        },
        "pressure": {
            "source_name": pressure_name,
            "reference_pa": reference_pressure.tolist(),
            "target_pa": target_pressure.tolist(),
            "interpolation": "linear in log(p)",
            "extrapolated_columns": 0,
        },
    }
    return output_path, target_pressure, reference_pressure, manifest


def dataset_pressure_units(path: Path, name: str) -> str | None:
    with h5py.File(path, "r") as handle:
        units = dataset_units(handle[name])
    # MJOLNIR drops attributes from its regrid files, but Pressure_mean is copied
    # from native THOR Pressure_mean, which is explicitly Pa.
    if units is None and name in {"Pressure", "Pressure_mean"}:
        return "Pa"
    return units


def append_manifest(path: Path, entries: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")


def copy_self(output_dir: Path) -> None:
    source = Path(__file__).resolve()
    destination = (output_dir / "scripts" / source.name).resolve()
    if source != destination:
        shutil.copy2(source, destination)


def main() -> int:
    args = parse_args()
    args.input_dir = args.input_dir.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()
    if args.input_dir == args.output_dir:
        raise ValueError("Input and output directories must differ")
    require_output_tree(args.output_dir)
    logger = setup_logging(args.output_dir)
    records = discover_records(args, logger)
    check_times(records, args.strict_time, logger)
    target_lat, target_lon = target_coordinates(
        args.latitude_step, args.longitude_step
    )

    target_pressure: np.ndarray | None = None
    reference_pressure: np.ndarray | None = None
    if args.pressure_levels_file:
        target_pressure = levels_from_file(args.pressure_levels_file)
        logger.info("Using pressure levels from %s", args.pressure_levels_file)

    manifest_entries: list[dict[str, Any]] = []
    outputs: list[Path] = []
    for record in records:
        expected_output = (
            args.output_dir
            / "standard_netcdf"
            / f"replat_{record.simulation_id}_{record.index:08d}.nc"
        )
        if expected_output.exists() and args.skip_existing:
            logger.info("Skipping existing verified/output file %s", expected_output)
            outputs.append(expected_output)
            continue
        output, target_pressure, reference_pressure, manifest = convert_one(
            record,
            args,
            target_lat,
            target_lon,
            target_pressure,
            reference_pressure,
            logger,
        )
        outputs.append(output)
        manifest_entries.append(manifest)

    if reference_pressure is not None and target_pressure is not None:
        write_pressure_mapping(
            args.output_dir / "validation" / "pressure_level_mapping.csv",
            reference_pressure,
            target_pressure,
        )
    elif not args.skip_existing:
        raise RuntimeError("No pressure mapping was created")
    if manifest_entries:
        append_manifest(
            args.output_dir / "logs" / "conversion_manifest.jsonl", manifest_entries
        )
    copy_self(args.output_dir)
    logger.info("Completed %d file(s): %s", len(outputs), ", ".join(map(str, outputs)))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.getLogger("thor_replat").exception("Conversion failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
