#!/usr/bin/env python3

"""Export THOR daily-mean winds to a CF-style pressure-level NetCDF.

This script reads raw THOR ``esp_output_<sim>_<index>.h5`` files together with
the precomputed ``regrid_map.npz`` horizontal weights and produces a single
regular latitude/longitude NetCDF file with dimensions:

    time x pressure x lat x lon

The output variables are the daily-mean wind components ``u``, ``v`` and ``w``
interpolated to a fixed pressure grid. The vertical interpolation follows the
same logic as ``THOR/mjolnir/hamarr.py``:

1. build daily-mean wind components from ``Mh_mean``, ``Wh_mean`` and
   ``Rho_mean``
2. horizontally interpolate from the native icosahedral grid to the regular
   lat/lon grid using ``regrid_map.npz``
3. vertically interpolate each column to a fixed pressure grid using linear
   interpolation in the instantaneous ``Pressure`` field, exactly as THOR's
   pressure regridding does

The default behavior is tuned for the Venus long run in this workspace:

    - select the last 5 Earth years at daily cadence
    - compute the pressure grid from the selected files using ``Pressure_mean``
    - stream the final dataset directly to NetCDF
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import h5py
import netCDF4
import numpy as np
from tqdm.auto import tqdm


CF_VERSION = "CF-1.10"
SCRIPT_NAME = "export_pressure_winds_netcdf.py"


@dataclass(frozen=True)
class GridInfo:
    point_num: int
    nv: int
    lon_native: np.ndarray
    lat_native: np.ndarray
    altitude: np.ndarray
    altitudeh: np.ndarray
    lon_regular: np.ndarray
    lat_regular: np.ndarray
    near3: np.ndarray
    weight3: np.ndarray

    @property
    def latlon_shape(self) -> tuple[int, int]:
        return (self.lat_regular.size, self.lon_regular.size)

    @property
    def ncol_regular(self) -> int:
        return self.lat_regular.size * self.lon_regular.size


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export THOR daily-mean winds to a pressure-level NetCDF."
    )
    parser.add_argument(
        "results_dir",
        type=Path,
        help="THOR results directory containing raw esp_output files and regrid_map.npz",
    )
    parser.add_argument(
        "--simulation-id",
        default="auto",
        help="Simulation identifier used in THOR filenames (default: auto-detect)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output NetCDF path. Default: <results_dir>/netcdf/<sim>_daily_mean_pressure_winds_last5y.nc",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Number of daily files to export. Overrides --earth-years.",
    )
    parser.add_argument(
        "--earth-years",
        type=float,
        default=5.0,
        help="Length of the export window in Earth years (default: 5.0).",
    )
    parser.add_argument(
        "--first-index",
        type=int,
        default=None,
        help="First THOR file index to include. If omitted, infer from last index and window length.",
    )
    parser.add_argument(
        "--last-index",
        type=int,
        default=None,
        help="Last THOR file index to include. If omitted, infer automatically.",
    )
    parser.add_argument(
        "--pressure-grid-txt",
        type=Path,
        default=None,
        help="Optional fixed pressure grid text file in THOR pgrid format.",
    )
    parser.add_argument(
        "--pressure-grid-h5",
        type=Path,
        default=None,
        help="Optional regridded THOR HDF5 file whose /Pressure dataset should be reused.",
    )
    parser.add_argument(
        "--compression-level",
        type=int,
        default=4,
        help="NetCDF zlib compression level (0-9). Default: 4.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the output NetCDF if it already exists.",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="Optional JSON sidecar with the export summary.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable tqdm progress bars.",
    )
    return parser.parse_args()


def fail(message: str) -> "NoReturn":
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def progress_iter(
    items: Iterable[int],
    *,
    enabled: bool,
    desc: str,
    total: int | None = None,
):
    if enabled:
        return tqdm(items, desc=desc, total=total, dynamic_ncols=True)
    return items


def infer_simulation_id(results_dir: Path) -> str:
    planet_files = sorted(results_dir.glob("esp_output_planet_*.h5"))
    if len(planet_files) != 1:
        found = ", ".join(path.name for path in planet_files) or "none"
        fail(
            "Could not auto-detect a unique simulation ID from esp_output_planet_*.h5. "
            f"Found: {found}"
        )
    match = re.fullmatch(r"esp_output_planet_(.+)\.h5", planet_files[0].name)
    if match is None:
        fail(f"Unexpected planet metadata filename: {planet_files[0].name}")
    return match.group(1)


def raw_file(results_dir: Path, simulation_id: str, index: int) -> Path:
    return results_dir / f"esp_output_{simulation_id}_{index}.h5"


def infer_output_stride_steps(results_dir: Path, simulation_id: str) -> int:
    global_path = results_dir / f"esp_global_{simulation_id}.txt"
    if not global_path.exists():
        return 288

    steps: list[int] = []
    with global_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split()
            steps.append(int(parts[0]))
            if len(steps) == 2:
                break
    if len(steps) < 2:
        return 288
    stride = steps[1] - steps[0]
    return stride if stride > 0 else 288


def infer_last_existing_index(results_dir: Path, simulation_id: str) -> int:
    stride_steps = infer_output_stride_steps(results_dir, simulation_id)
    global_path = results_dir / f"esp_global_{simulation_id}.txt"
    if not global_path.exists():
        fail(
            f"Cannot infer last index automatically because {global_path.name} is missing. "
            "Pass --last-index explicitly."
        )

    last_step = None
    with global_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            last_step = int(line.split()[0])
    if last_step is None:
        fail(f"No data rows found in {global_path}")

    candidate = last_step // stride_steps + 1
    for index in range(candidate, -1, -1):
        if raw_file(results_dir, simulation_id, index).exists():
            return index
    fail("Could not find any raw esp_output files while inferring the last index.")


def select_indices(
    results_dir: Path,
    simulation_id: str,
    first_index: int,
    last_index: int,
) -> tuple[list[int], list[int]]:
    available: list[int] = []
    missing: list[int] = []
    for index in range(first_index, last_index + 1):
        if raw_file(results_dir, simulation_id, index).exists():
            available.append(index)
        else:
            missing.append(index)
    if not available:
        fail(
            f"No raw files found for the requested index range {first_index}..{last_index}."
        )
    return available, missing


def load_grid(results_dir: Path, simulation_id: str) -> GridInfo:
    grid_path = results_dir / f"esp_output_grid_{simulation_id}.h5"
    map_path = results_dir / "regrid_map.npz"
    if not grid_path.exists():
        fail(f"Missing grid file: {grid_path}")
    if not map_path.exists():
        fail(f"Missing regrid map: {map_path}")

    with h5py.File(grid_path, "r") as h5:
        point_num = int(h5["point_num"][0])
        nv = int(h5["nv"][0])
        lonlat = np.asarray(h5["lonlat"][:], dtype=np.float64)
        lon_native = lonlat[::2] % (2 * np.pi)
        lat_native = lonlat[1::2]
        altitude = np.asarray(h5["Altitude"][:], dtype=np.float64)
        altitudeh = np.asarray(h5["Altitudeh"][:], dtype=np.float64)

    rg_map = np.load(map_path)
    lon_regular = np.asarray(rg_map["lon"], dtype=np.float64)
    lat_regular = np.asarray(rg_map["lat"], dtype=np.float64)
    near3 = np.asarray(rg_map["near3"], dtype=np.int64)
    weight3 = np.asarray(rg_map["weight3"], dtype=np.float64)

    return GridInfo(
        point_num=point_num,
        nv=nv,
        lon_native=lon_native,
        lat_native=lat_native,
        altitude=altitude,
        altitudeh=altitudeh,
        lon_regular=lon_regular,
        lat_regular=lat_regular,
        near3=near3,
        weight3=weight3,
    )


def read_pressure_grid_from_h5(path: Path) -> np.ndarray:
    with h5py.File(path, "r") as h5:
        if "Pressure" not in h5:
            fail(f"{path} does not contain a /Pressure dataset.")
        return np.asarray(h5["Pressure"][:], dtype=np.float64)


def compute_mean_pressure_grid(
    results_dir: Path,
    simulation_id: str,
    grid: GridInfo,
    indices: Iterable[int],
    *,
    show_progress: bool,
) -> np.ndarray:
    index_list = list(indices)
    pressure_sum = np.zeros(grid.nv, dtype=np.float64)
    sample_count = 0
    iterator = progress_iter(
        index_list,
        enabled=show_progress,
        desc="Building pressure grid",
        total=len(index_list),
    )
    for position, index in enumerate(iterator, start=1):
        with h5py.File(raw_file(results_dir, simulation_id, index), "r") as h5:
            pressure_mean = np.asarray(h5["Pressure_mean"][:], dtype=np.float64).reshape(
                grid.point_num, grid.nv
            )
        pressure_sum += pressure_mean.mean(axis=0)
        sample_count += 1
        if not show_progress and (position % 100 == 0 or position == len(index_list)):
            print(
                f"[pgrid {position}/{len(index_list)}] processed source index {index}",
                flush=True,
            )
    if sample_count == 0:
        fail("Cannot build a pressure grid because no samples were selected.")
    return pressure_sum / sample_count


def load_raw_mean_fields(
    results_dir: Path,
    simulation_id: str,
    grid: GridInfo,
    index: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    path = raw_file(results_dir, simulation_id, index)
    with h5py.File(path, "r") as h5:
        rho_mean = np.asarray(h5["Rho_mean"][:], dtype=np.float64).reshape(
            grid.point_num, grid.nv
        )
        pressure = np.asarray(h5["Pressure"][:], dtype=np.float64).reshape(
            grid.point_num, grid.nv
        )
        pressure_mean = np.asarray(h5["Pressure_mean"][:], dtype=np.float64).reshape(
            grid.point_num, grid.nv
        )

        mh_flat = np.asarray(h5["Mh_mean"][:], dtype=np.float64)
        mh_mean = np.empty((3, grid.point_num, grid.nv), dtype=np.float64)
        mh_mean[0] = mh_flat[::3].reshape(grid.point_num, grid.nv)
        mh_mean[1] = mh_flat[1::3].reshape(grid.point_num, grid.nv)
        mh_mean[2] = mh_flat[2::3].reshape(grid.point_num, grid.nv)

        wh_mean = np.asarray(h5["Wh_mean"][:], dtype=np.float64).reshape(
            grid.point_num, grid.nv + 1
        )
        simulation_time_days = float(h5["simulation_time"][0]) / 86400.0

    return rho_mean, pressure, pressure_mean, mh_mean, wh_mean, simulation_time_days


def build_daily_mean_winds(
    grid: GridInfo,
    rho_mean: np.ndarray,
    mh_mean: np.ndarray,
    wh_mean: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    interpz = (grid.altitude - grid.altitudeh[:-1]) / (
        grid.altitudeh[1:] - grid.altitudeh[:-1]
    )

    u = (
        -mh_mean[0] * np.sin(grid.lon_native[:, None])
        + mh_mean[1] * np.cos(grid.lon_native[:, None])
    ) / rho_mean
    v = (
        -mh_mean[0]
        * np.sin(grid.lat_native[:, None])
        * np.cos(grid.lon_native[:, None])
        - mh_mean[1]
        * np.sin(grid.lat_native[:, None])
        * np.sin(grid.lon_native[:, None])
        + mh_mean[2] * np.cos(grid.lat_native[:, None])
    ) / rho_mean
    w = (
        wh_mean[:, :-1]
        + (wh_mean[:, 1:] - wh_mean[:, :-1]) * interpz[None, :]
    ) / rho_mean

    return u, v, w


def horizontal_regrid(grid: GridInfo, source: np.ndarray) -> np.ndarray:
    tmp = np.sum(grid.weight3[:, :, None] * source[grid.near3], axis=1)
    return tmp.reshape((*grid.latlon_shape, source.shape[-1]))


def prepare_pressure_interpolation(
    pressure_ll: np.ndarray,
    pressure_levels: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    nlat, nlon, nz = pressure_ll.shape
    ncol = nlat * nlon
    p_src = pressure_ll.reshape(ncol, nz)[:, ::-1]
    p_new = pressure_levels[::-1]
    col_index = np.arange(ncol)

    if np.any(np.diff(p_src, axis=1) < 0):
        fail("Encountered non-monotonic pressure columns during interpolation.")
    if np.any(np.diff(p_new) < 0):
        fail("Destination pressure grid is not monotonic.")

    interval_index = np.empty((ncol, p_new.size), dtype=np.int64)
    alpha = np.empty((ncol, p_new.size), dtype=np.float64)
    for level, p_target in enumerate(p_new):
        # Match THOR's hamarr.regrid interval selection exactly: when the target
        # pressure lands on a source level, use the segment below that knot.
        idx = np.sum(p_src < p_target, axis=1) - 1
        idx = np.clip(idx, 0, nz - 2)
        p0 = p_src[col_index, idx]
        p1 = p_src[col_index, idx + 1]
        denom = p1 - p0
        weight = np.zeros_like(p0)
        np.divide(
            p_target - p0,
            denom,
            out=weight,
            where=denom != 0,
        )
        interval_index[:, level] = idx
        alpha[:, level] = weight
    return interval_index, alpha


def apply_pressure_interpolation(
    field_ll: np.ndarray,
    interval_index: np.ndarray,
    alpha: np.ndarray,
) -> np.ndarray:
    nlat, nlon, nz = field_ll.shape
    ncol = nlat * nlon
    field_src = field_ll.reshape(ncol, nz)[:, ::-1]
    col_index = np.arange(ncol)[:, None]
    interp_rev = field_src[col_index, interval_index] + alpha * (
        field_src[col_index, interval_index + 1]
        - field_src[col_index, interval_index]
    )
    return interp_rev[:, ::-1].reshape(nlat, nlon, interval_index.shape[1])


def create_netcdf(
    output_path: Path,
    grid: GridInfo,
    pressure_levels: np.ndarray,
    compression_level: int,
    simulation_id: str,
    summary: dict[str, object],
) -> netCDF4.Dataset:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fill = np.float32(np.nan)
    nc = netCDF4.Dataset(output_path, "w", format="NETCDF4")

    nc.createDimension("time", None)
    nc.createDimension("pressure", pressure_levels.size)
    nc.createDimension("lat", grid.lat_regular.size)
    nc.createDimension("lon", grid.lon_regular.size)

    time_var = nc.createVariable("time", "f8", ("time",))
    time_var.standard_name = "time"
    time_var.long_name = "Synthetic CF-compatible time axis"
    time_var.units = "days since 0001-01-01 00:00:00"
    time_var.calendar = "proleptic_gregorian"
    time_var.comment = (
        "This axis is anchored to a synthetic epoch only for CF compatibility. "
        "Use simulation_day for the physically meaningful model time since start."
    )
    time_var.axis = "T"

    simulation_day_var = nc.createVariable("simulation_day", "f8", ("time",))
    simulation_day_var.long_name = "Simulation time since model start"
    simulation_day_var.units = "days"

    file_index_var = nc.createVariable("source_file_index", "i4", ("time",))
    file_index_var.long_name = "THOR esp_output file index"

    pressure_var = nc.createVariable("pressure", "f8", ("pressure",))
    pressure_var.standard_name = "air_pressure"
    pressure_var.long_name = "Fixed pressure coordinate"
    pressure_var.units = "Pa"
    pressure_var.positive = "down"
    pressure_var.axis = "Z"
    pressure_var[:] = pressure_levels

    lat_var = nc.createVariable("lat", "f8", ("lat",))
    lat_var.standard_name = "latitude"
    lat_var.long_name = "Latitude"
    lat_var.units = "degrees_north"
    lat_var.axis = "Y"
    lat_var[:] = np.rad2deg(grid.lat_regular)

    lon_var = nc.createVariable("lon", "f8", ("lon",))
    lon_var.standard_name = "longitude"
    lon_var.long_name = "Longitude"
    lon_var.units = "degrees_east"
    lon_var.axis = "X"
    lon_var[:] = np.rad2deg(grid.lon_regular)

    chunking = (1, pressure_levels.size, grid.lat_regular.size, grid.lon_regular.size)
    for name, standard_name, long_name in (
        ("u", "eastward_wind", "Daily mean eastward wind"),
        ("v", "northward_wind", "Daily mean northward wind"),
        ("w", "upward_air_velocity", "Daily mean vertical velocity"),
    ):
        var = nc.createVariable(
            name,
            "f4",
            ("time", "pressure", "lat", "lon"),
            zlib=True,
            complevel=compression_level,
            shuffle=True,
            fill_value=fill,
            chunksizes=chunking,
        )
        var.standard_name = standard_name
        var.long_name = long_name
        var.units = "m s-1"
        var.coordinates = "simulation_day"
        var.cell_methods = "time: mean (interval: 1 day)"

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nc.Conventions = CF_VERSION
    nc.title = "THOR Venus daily-mean winds on fixed pressure levels"
    nc.summary = (
        "Daily-mean u, v and w wind components interpolated from THOR raw outputs "
        "to a regular latitude/longitude grid and a fixed pressure grid."
    )
    nc.source = "THOR raw esp_output HDF5 files"
    nc.history = f"{timestamp}: created with {SCRIPT_NAME}"
    nc.thor_simulation_id = simulation_id
    nc.horizontal_regrid = "Barycentric interpolation using results_dir/regrid_map.npz"
    nc.vertical_regrid = (
        "Column-wise linear interpolation in instantaneous Pressure following "
        "THOR hamarr.regrid"
    )
    nc.wind_source_fields = "Mh_mean, Wh_mean, Rho_mean"
    nc.pressure_coordinate_field = "Pressure"
    nc.pressure_grid_source_field = "Pressure_mean"
    for key, value in summary.items():
        if isinstance(value, (str, int, float)):
            setattr(nc, key, value)
    return nc


def default_output_path(results_dir: Path, simulation_id: str) -> Path:
    return results_dir / "netcdf" / f"{simulation_id}_daily_mean_pressure_winds_last5y.nc"


def write_summary_json(path: Path, summary: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)


def main() -> None:
    args = parse_args()
    results_dir = args.results_dir.resolve()
    if not results_dir.exists():
        fail(f"Results directory does not exist: {results_dir}")

    simulation_id = (
        infer_simulation_id(results_dir)
        if args.simulation_id == "auto"
        else args.simulation_id
    )
    grid = load_grid(results_dir, simulation_id)

    if args.last_index is None:
        last_index = infer_last_existing_index(results_dir, simulation_id)
    else:
        last_index = args.last_index

    if args.days is not None:
        window_days = args.days
    else:
        window_days = int(round(args.earth_years * 365.25))
    if window_days <= 0:
        fail("The requested window length must be positive.")

    if args.first_index is None:
        first_index = max(0, last_index - window_days + 1)
    else:
        first_index = args.first_index
    if first_index > last_index:
        fail("first-index cannot be greater than last-index.")

    available_indices, missing_indices = select_indices(
        results_dir, simulation_id, first_index, last_index
    )

    if args.pressure_grid_txt is not None:
        pressure_levels = np.loadtxt(args.pressure_grid_txt, usecols=1, dtype=np.float64)
        pressure_grid_source = str(args.pressure_grid_txt.resolve())
    elif args.pressure_grid_h5 is not None:
        pressure_levels = read_pressure_grid_from_h5(args.pressure_grid_h5)
        pressure_grid_source = str(args.pressure_grid_h5.resolve())
    else:
        pressure_levels = compute_mean_pressure_grid(
            results_dir,
            simulation_id,
            grid,
            available_indices,
            show_progress=not args.no_progress,
        )
        pressure_grid_source = "mean(Pressure_mean) over selected raw files"
    print(
        f"Pressure grid ready with {pressure_levels.size} levels from {pressure_grid_source}",
        flush=True,
    )

    output_path = (
        args.output.resolve()
        if args.output is not None
        else default_output_path(results_dir, simulation_id)
    )
    if output_path.exists() and not args.overwrite:
        fail(f"Output already exists: {output_path}. Use --overwrite to replace it.")

    summary: dict[str, object] = {
        "results_dir": str(results_dir),
        "simulation_id": simulation_id,
        "requested_first_index": first_index,
        "requested_last_index": last_index,
        "available_samples": len(available_indices),
        "missing_samples": len(missing_indices),
        "first_available_index": available_indices[0],
        "last_available_index": available_indices[-1],
        "pressure_levels": int(pressure_levels.size),
        "lat_points": int(grid.lat_regular.size),
        "lon_points": int(grid.lon_regular.size),
        "pressure_grid_source": pressure_grid_source,
    }

    print(
        (
            f"Preparing export for {len(available_indices)} available daily files "
            f"({available_indices[0]}..{available_indices[-1]}); "
            f"missing inside requested window: {len(missing_indices)}"
        ),
        flush=True,
    )

    nc = create_netcdf(
        output_path=output_path,
        grid=grid,
        pressure_levels=pressure_levels,
        compression_level=args.compression_level,
        simulation_id=simulation_id,
        summary=summary,
    )
    try:
        u_var = nc.variables["u"]
        v_var = nc.variables["v"]
        w_var = nc.variables["w"]
        time_var = nc.variables["time"]
        simulation_day_var = nc.variables["simulation_day"]
        file_index_var = nc.variables["source_file_index"]

        iterator = progress_iter(
            available_indices,
            enabled=not args.no_progress,
            desc="Writing NetCDF",
            total=len(available_indices),
        )
        for time_index, source_index in enumerate(iterator):
            rho_mean, pressure, pressure_mean, mh_mean, wh_mean, simulation_time_days = load_raw_mean_fields(
                results_dir, simulation_id, grid, source_index
            )
            u_ico, v_ico, w_ico = build_daily_mean_winds(grid, rho_mean, mh_mean, wh_mean)

            pressure_ll = horizontal_regrid(grid, pressure)
            interval_index, alpha = prepare_pressure_interpolation(
                pressure_ll, pressure_levels
            )

            u_ll = horizontal_regrid(grid, u_ico)
            v_ll = horizontal_regrid(grid, v_ico)
            w_ll = horizontal_regrid(grid, w_ico)

            u_press = apply_pressure_interpolation(u_ll, interval_index, alpha)
            v_press = apply_pressure_interpolation(v_ll, interval_index, alpha)
            w_press = apply_pressure_interpolation(w_ll, interval_index, alpha)

            time_var[time_index] = simulation_time_days
            simulation_day_var[time_index] = simulation_time_days
            file_index_var[time_index] = source_index
            u_var[time_index, :, :, :] = np.transpose(u_press, (2, 0, 1)).astype(np.float32)
            v_var[time_index, :, :, :] = np.transpose(v_press, (2, 0, 1)).astype(np.float32)
            w_var[time_index, :, :, :] = np.transpose(w_press, (2, 0, 1)).astype(np.float32)

            if args.no_progress and (
                (time_index + 1) % 25 == 0 or time_index == len(available_indices) - 1
            ):
                print(
                    f"[{time_index + 1}/{len(available_indices)}] wrote source index {source_index}",
                    flush=True,
                )
    finally:
        nc.close()

    if args.summary_json is not None:
        summary_path = args.summary_json.resolve()
    else:
        summary_path = output_path.with_suffix(output_path.suffix + ".summary.json")
    summary["output_path"] = str(output_path)
    summary["summary_json"] = str(summary_path)
    summary["missing_index_preview"] = missing_indices[:50]
    write_summary_json(summary_path, summary)

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
