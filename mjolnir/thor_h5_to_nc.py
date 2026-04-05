#!/usr/bin/env python3

"""Convert THOR mjolnir regridded HDF5 output into CF-style NetCDF.

This converter targets the *regridded* THOR files produced by
`mjolnir/regrid.py`, for example:

  - `regrid_<simulation>_<index>.h5`      (pressure coordinate)
  - `regrid_height_<simulation>_<index>.h5` (altitude coordinate)

It does not convert raw `esp_output_*.h5` dumps directly, because those files
are still on THOR's native icosahedral grid and need semantic regridding first.

The original positional interface is preserved:

    python3 thor_h5_to_nc.py input.h5 output.nc

If no output file is given, the converter writes to a sibling dedicated folder
named after the input folder plus `_nc`, for example:

    pgrid_0_2000_1/regrid_venus_0.h5
    -> pgrid_0_2000_1_nc/regrid_venus_0.nc

Optional validation can be enabled with:

    python3 thor_h5_to_nc.py input.h5 --validate

NetCDF compression is off by default. Enable it explicitly with:

    python3 thor_h5_to_nc.py input.h5 --compression-level 4
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import re
import sys
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import xarray as xr


CF_VERSION = "CF-1.8"
THOR_REPO_URL = "https://github.com/exoclime/THOR"


CORE_VAR_ATTRS: dict[str, dict[str, Any]] = {
    "Temperature": {
        "standard_name": "air_temperature",
        "long_name": "Air temperature",
        "units": "K",
    },
    "U": {
        "standard_name": "eastward_wind",
        "long_name": "Eastward wind",
        "units": "m s-1",
    },
    "V": {
        "standard_name": "northward_wind",
        "long_name": "Northward wind",
        "units": "m s-1",
    },
    "W": {
        "long_name": "Vertical velocity",
        "units": "m s-1",
    },
    "Rho": {
        "standard_name": "air_density",
        "long_name": "Air density",
        "units": "kg m-3",
    },
    "Pressure_mean": {
        "standard_name": "air_pressure",
        "long_name": "Mean air pressure",
        "units": "Pa",
    },
    "Rho_mean": {
        "standard_name": "air_density",
        "long_name": "Mean air density",
        "units": "kg m-3",
    },
    "Cp": {
        "long_name": "Specific heat capacity at constant pressure",
        "units": "J kg-1 K-1",
    },
    "Rd": {
        "long_name": "Gas constant of air",
        "units": "J kg-1 K-1",
    },
    "PV": {
        "long_name": "Potential vorticity",
    },
    "RVu": {
        "long_name": "Relative vorticity, zonal component",
        "units": "s-1",
    },
    "RVv": {
        "long_name": "Relative vorticity, meridional component",
        "units": "s-1",
    },
    "RVw": {
        "long_name": "Relative vorticity, vertical component",
        "units": "s-1",
    },
    "flw_up": {
        "long_name": "Upward longwave radiative flux",
        "units": "W m-2",
    },
    "flw_dn": {
        "long_name": "Downward longwave radiative flux",
        "units": "W m-2",
    },
    "fsw_up": {
        "long_name": "Upward shortwave radiative flux",
        "units": "W m-2",
    },
    "fsw_dn": {
        "long_name": "Downward shortwave radiative flux",
        "units": "W m-2",
    },
    "DGf_net": {
        "long_name": "Net double-gray radiative flux",
        "units": "W m-2",
    },
    "tau_sw": {
        "long_name": "Layer shortwave optical depth",
        "units": "1",
    },
    "tau_lw": {
        "long_name": "Layer longwave optical depth",
        "units": "1",
    },
    "qheat": {
        "long_name": "Physics-module heating power density",
        "units": "W m-3",
    },
    "DGqheat": {
        "long_name": "Double-gray radiative heating term",
    },
    "insol": {
        "long_name": "Instantaneous insolation",
        "units": "W m-2",
    },
    "insol_annual": {
        "long_name": "Orbit-averaged insolation",
        "units": "W m-2",
    },
    "Etotal": {
        "long_name": "Total energy",
        "units": "kg m2 s-2",
    },
    "Entropy": {
        "long_name": "Entropy",
        "units": "kg m2 s-2 K-1",
    },
    "AngMomz": {
        "long_name": "Angular momentum about planetary rotation axis",
        "units": "kg m2 s-1",
    },
    "Tsurface": {
        "long_name": "Surface temperature",
        "units": "K",
    },
    "Psurf": {
        "long_name": "Surface pressure",
        "units": "Pa",
    },
    "KH": {
        "long_name": "Turbulent diffusion coefficient for heat",
        "units": "m2 s-1",
    },
    "KM": {
        "long_name": "Turbulent diffusion coefficient for momentum",
        "units": "m2 s-1",
    },
    "CM": {
        "long_name": "Surface drag coefficient",
        "units": "1",
    },
    "CH": {
        "long_name": "Surface heat-transfer coefficient",
        "units": "1",
    },
    "F_sens": {
        "long_name": "Surface to atmosphere sensible heat flux",
        "units": "W m-2",
    },
}


RAW_SCALAR_ATTR_MAP = {
    "nstep": "thor_nstep",
    "simulation_time": "thor_simulation_time_s",
    "A": "thor_planet_radius_m",
    "P_Ref": "thor_reference_pressure_pa",
    "Gravit": "thor_surface_gravity_m_s2",
    "Omega": "thor_rotation_rate_s-1",
    "Top_altitude": "thor_model_top_altitude_m",
    "DeepModel": "thor_deep_model_flag",
    "core_benchmark": "thor_core_benchmark",
    "phy_module": "thor_physics_module",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert THOR mjolnir regridded HDF5 output into CF-style NetCDF."
    )
    parser.add_argument("infile", type=Path, help="Input regridded THOR HDF5 file")
    parser.add_argument(
        "outfile",
        type=Path,
        nargs="?",
        help=(
            "Optional output NetCDF file. If omitted, a sibling dedicated folder "
            "named <input_dir>_nc is created automatically."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Optional output directory. The NetCDF filename will be derived from the "
            "input filename."
        ),
    )
    parser.add_argument(
        "--source-raw",
        type=Path,
        help="Optional matching raw THOR esp_output_*.h5 file for extra metadata",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional NetCDF global title",
    )
    parser.add_argument(
        "--simulation-id",
        default=None,
        help="Optional THOR simulation identifier override",
    )
    parser.add_argument(
        "--compression-level",
        type=int,
        default=None,
        help="NetCDF zlib compression level (0-9). Default is no compression.",
    )
    parser.add_argument(
        "--no-compression",
        action="store_true",
        help="Disable zlib compression in the NetCDF output",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Re-open the written NetCDF and compare it against the HDF5 source",
    )
    return parser.parse_args()


def fail(message: str) -> "NoReturn":
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def sanitize_dim_name(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]+", "_", name).strip("_").lower() or "dim"


def to_python_scalar(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray) and value.shape == ():
        return value.item()
    return value


def infer_simulation_id_and_index(path: Path) -> tuple[str | None, str | None]:
    match = re.match(r"regrid(?:_height)?_([^_]+)_(\d+)\.h5$", path.name)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def infer_matching_raw_file(infile: Path) -> Path | None:
    sim_id, index = infer_simulation_id_and_index(infile)
    if index is None:
        return None

    search_dirs = [infile.parent, infile.parent.parent]
    seen: set[Path] = set()
    candidates: list[Path] = []

    for directory in search_dirs:
        if directory in seen or not directory.exists():
            continue
        seen.add(directory)
        if sim_id is not None:
            direct = directory / f"esp_output_{sim_id}_{index}.h5"
            if direct.exists():
                return direct
        candidates.extend(sorted(directory.glob(f"esp_output_*_{index}.h5")))

    if len(candidates) == 1:
        return candidates[0]
    return None


def default_output_dir(infile: Path) -> Path:
    parent = infile.parent
    return parent.with_name(f"{parent.name}_nc")


def resolve_output_path(
    infile: Path,
    outfile: Path | None,
    output_dir: Path | None,
) -> Path:
    if outfile is not None and output_dir is not None:
        fail("use either an explicit outfile or --output-dir, not both")

    if outfile is not None:
        return outfile

    target_dir = output_dir if output_dir is not None else default_output_dir(infile)
    return target_dir / f"{infile.stem}.nc"


def read_raw_metadata(raw_path: Path | None) -> dict[str, Any]:
    if raw_path is None or not raw_path.exists():
        return {}

    metadata: dict[str, Any] = {"thor_raw_source": str(raw_path)}
    with h5py.File(raw_path, "r") as h5:
        for h5_name, attr_name in RAW_SCALAR_ATTR_MAP.items():
            if h5_name not in h5:
                continue
            value = h5[h5_name][...]
            value = to_python_scalar(value)
            metadata[attr_name] = value
    return metadata


def detect_vertical_coordinate(h5: h5py.File) -> tuple[str, str, np.ndarray, dict[str, str]]:
    if "Pressure" in h5 and h5["Pressure"].ndim == 1:
        values = np.asarray(h5["Pressure"][:], dtype=np.float64)
        attrs = {
            "standard_name": "air_pressure",
            "long_name": "Pressure coordinate",
            "units": "Pa",
            "positive": "down",
            "axis": "Z",
        }
        return "Pressure", "pressure", values, attrs

    if "Altitude" in h5 and h5["Altitude"].ndim == 1:
        values = np.asarray(h5["Altitude"][:], dtype=np.float64)
        attrs = {
            "standard_name": "altitude",
            "long_name": "Altitude coordinate",
            "units": "m",
            "positive": "up",
            "axis": "Z",
        }
        return "Altitude", "altitude", values, attrs

    fail(
        "input does not look like THOR mjolnir regridded output. "
        "Expected 1D 'Pressure' or 'Altitude' plus 1D 'Latitude'/'Longitude'. "
        "Raw esp_output_*.h5 files must be regridded first."
    )


def build_variable_attrs(name: str) -> dict[str, Any]:
    attrs = dict(CORE_VAR_ATTRS.get(name, {}))

    if not attrs and name.endswith("_mean"):
        base_name = name[: -len("_mean")]
        base_attrs = CORE_VAR_ATTRS.get(base_name, {})
        if base_attrs:
            attrs = dict(base_attrs)
            attrs["long_name"] = f"Mean {base_attrs.get('long_name', base_name).lower()}"

    if name.endswith("_mean"):
        attrs.setdefault("cell_methods", "time: mean")

    return attrs


def convert_dataset(
    infile: Path,
    outfile: Path,
    raw_path: Path | None = None,
    title: str | None = None,
    simulation_id_override: str | None = None,
    compression_level: int = 4,
    use_compression: bool = True,
) -> xr.Dataset:
    if not infile.exists():
        fail(f"input file does not exist: {infile}")

    outfile.parent.mkdir(parents=True, exist_ok=True)

    raw_path = raw_path if raw_path is not None else infer_matching_raw_file(infile)
    raw_meta = read_raw_metadata(raw_path)
    inferred_simulation_id, _ = infer_simulation_id_and_index(infile)
    simulation_id = simulation_id_override or inferred_simulation_id

    with h5py.File(infile, "r") as h5:
        if "Latitude" not in h5 or "Longitude" not in h5:
            fail(
                "input is missing 1D 'Latitude'/'Longitude' datasets and is not a supported "
                "regridded THOR file."
            )

        lat = np.asarray(h5["Latitude"][:], dtype=np.float64)
        lon = np.asarray(h5["Longitude"][:], dtype=np.float64)
        vertical_h5_name, vertical_name, vertical_values, vertical_attrs = detect_vertical_coordinate(h5)

        coords: dict[str, tuple[Any, Any, dict[str, Any]]] = {
            "lat": (
                "lat",
                lat,
                {
                    "standard_name": "latitude",
                    "long_name": "Latitude",
                    "units": "degrees_north",
                    "axis": "Y",
                },
            ),
            "lon": (
                "lon",
                lon,
                {
                    "standard_name": "longitude",
                    "long_name": "Longitude",
                    "units": "degrees_east",
                    "axis": "X",
                },
            ),
            vertical_name: (vertical_name, vertical_values, vertical_attrs),
        }

        data_vars: dict[str, tuple[Any, Any, dict[str, Any]]] = {}
        generic_dim_coords: dict[str, np.ndarray] = {}

        nlat = lat.size
        nlon = lon.size
        nz = vertical_values.size

        for name in h5.keys():
            if name in {"Latitude", "Longitude", vertical_h5_name}:
                continue

            arr = np.asarray(h5[name][...])
            attrs = build_variable_attrs(name)

            if arr.ndim == 3 and arr.shape == (nlat, nlon, nz):
                data_vars[name] = ((vertical_name, "lat", "lon"), np.transpose(arr, (2, 0, 1)), attrs)
                continue

            if arr.ndim == 3 and arr.shape == (nz, nlat, nlon):
                data_vars[name] = ((vertical_name, "lat", "lon"), arr, attrs)
                continue

            if arr.ndim == 2 and arr.shape == (nlat, nlon):
                data_vars[name] = (("lat", "lon"), arr, attrs)
                continue

            if arr.ndim == 1 and arr.shape == (nz,):
                data_vars[name] = ((vertical_name,), arr, attrs)
                continue

            if arr.ndim == 1 and arr.shape == (1,):
                data_vars[name] = ((), to_python_scalar(arr[0]), attrs)
                continue

            if arr.ndim == 0:
                data_vars[name] = ((), to_python_scalar(arr), attrs)
                continue

            dims: list[str] = []
            for axis, size in enumerate(arr.shape):
                dim_name = f"{sanitize_dim_name(name)}_dim_{axis}"
                dims.append(dim_name)
                if dim_name not in generic_dim_coords:
                    generic_dim_coords[dim_name] = np.arange(size, dtype=np.int32)
            data_vars[name] = (tuple(dims), arr, attrs)

        for dim_name, coord_values in generic_dim_coords.items():
            coords[dim_name] = (dim_name, coord_values, {"long_name": dim_name})

        ds = xr.Dataset(data_vars=data_vars, coords=coords)

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ds.attrs.update(
        {
            "Conventions": CF_VERSION,
            "title": title or "THOR mjolnir regridded output converted to CF-style NetCDF",
            "source": "THOR mjolnir regridded HDF5 output",
            "history": f"{timestamp}: converted from {infile.name} with thor_h5_to_nc.py",
            "references": THOR_REPO_URL,
            "input_hdf5_file": str(infile),
            "vertical_coordinate": vertical_name,
        }
    )

    if simulation_id is not None:
        ds.attrs["thor_simulation_id"] = simulation_id

    for key, value in raw_meta.items():
        ds.attrs[key] = to_python_scalar(value)

    encoding: dict[str, dict[str, Any]] = {}
    for coord_name in ds.coords:
        encoding[coord_name] = {"_FillValue": None}

    for var_name, data_var in ds.data_vars.items():
        var_encoding: dict[str, Any] = {}
        if np.issubdtype(data_var.dtype, np.floating):
            var_encoding["_FillValue"] = np.float64(np.nan)
        else:
            var_encoding["_FillValue"] = None

        if use_compression and data_var.ndim > 0:
            var_encoding["zlib"] = True
            var_encoding["complevel"] = compression_level
            var_encoding["shuffle"] = True

        encoding[var_name] = var_encoding

    ds.to_netcdf(
        outfile,
        engine="netcdf4",
        format="NETCDF4",
        encoding=encoding,
    )
    return ds


def compare_arrays(reference: np.ndarray, candidate: np.ndarray) -> tuple[bool, float]:
    if reference.shape != candidate.shape:
        return False, math.inf
    if np.allclose(reference, candidate, rtol=0.0, atol=0.0, equal_nan=True):
        return True, 0.0

    ref_mask = np.isfinite(reference)
    cand_mask = np.isfinite(candidate)
    common = ref_mask & cand_mask
    max_abs_diff = 0.0
    if np.any(common):
        max_abs_diff = float(np.max(np.abs(reference[common] - candidate[common])))
    else:
        max_abs_diff = math.inf
    return False, max_abs_diff


def validate_output(infile: Path, outfile: Path) -> dict[str, Any]:
    with h5py.File(infile, "r") as h5, xr.open_dataset(outfile) as ds:
        vertical_h5_name, vertical_name, vertical_values, _ = detect_vertical_coordinate(h5)
        lat = np.asarray(h5["Latitude"][:], dtype=np.float64)
        lon = np.asarray(h5["Longitude"][:], dtype=np.float64)

        checks: list[str] = []
        issues: list[str] = []

        ok, diff = compare_arrays(lat, ds["lat"].values)
        checks.append("lat")
        if not ok:
            issues.append(f"Latitude mismatch (max abs diff {diff})")

        ok, diff = compare_arrays(lon, ds["lon"].values)
        checks.append("lon")
        if not ok:
            issues.append(f"Longitude mismatch (max abs diff {diff})")

        ok, diff = compare_arrays(vertical_values, ds[vertical_name].values)
        checks.append(vertical_name)
        if not ok:
            issues.append(f"{vertical_name} mismatch (max abs diff {diff})")

        if ds.attrs.get("Conventions") != CF_VERSION:
            issues.append(f"Conventions attribute is {ds.attrs.get('Conventions')!r}, expected {CF_VERSION!r}")
        if ds["lat"].attrs.get("standard_name") != "latitude":
            issues.append("lat coordinate is missing standard_name=latitude")
        if ds["lon"].attrs.get("standard_name") != "longitude":
            issues.append("lon coordinate is missing standard_name=longitude")
        if "axis" not in ds[vertical_name].attrs:
            issues.append(f"{vertical_name} coordinate is missing axis metadata")

        nlat = lat.size
        nlon = lon.size
        nz = vertical_values.size
        compared_vars = 0

        for name in h5.keys():
            if name in {"Latitude", "Longitude", vertical_h5_name}:
                continue

            if name not in ds:
                issues.append(f"Missing variable in NetCDF output: {name}")
                continue

            arr = np.asarray(h5[name][...])
            nc = ds[name].values

            if arr.ndim == 3 and arr.shape == (nlat, nlon, nz):
                ref = np.transpose(arr, (2, 0, 1))
            elif arr.ndim == 3 and arr.shape == (nz, nlat, nlon):
                ref = arr
            elif arr.ndim == 2 and arr.shape == (nlat, nlon):
                ref = arr
            elif arr.ndim == 1 and arr.shape == (nz,):
                ref = arr
            elif arr.ndim == 1 and arr.shape == (1,):
                ref = np.asarray(arr[0])
            elif arr.ndim == 0:
                ref = np.asarray(arr)
            else:
                # Generic-dimension variables are preserved, but the benchmark focuses on
                # the standard THOR regrid fields used in the current workflow.
                continue

            ok, diff = compare_arrays(np.asarray(ref), np.asarray(nc))
            compared_vars += 1
            if not ok:
                issues.append(f"Variable mismatch for {name} (max abs diff {diff})")

        return {
            "passed": not issues,
            "checks_run": len(checks) + compared_vars,
            "variables_compared": compared_vars,
            "issues": issues,
        }


def main() -> None:
    args = parse_args()
    output_path = resolve_output_path(args.infile, args.outfile, args.output_dir)

    if args.no_compression and args.compression_level is not None:
        fail("use either --compression-level or --no-compression, not both")

    if args.no_compression or args.compression_level is None:
        use_compression = False
    else:
        if not 0 <= args.compression_level <= 9:
            fail("--compression-level must be between 0 and 9")
        use_compression = True

    ds = convert_dataset(
        infile=args.infile,
        outfile=output_path,
        raw_path=args.source_raw,
        title=args.title,
        simulation_id_override=args.simulation_id,
        compression_level=args.compression_level,
        use_compression=use_compression,
    )

    print(f"Converted: {output_path}")
    print(
        "Summary: "
        f"dims={dict(ds.sizes)} "
        f"data_vars={len(ds.data_vars)} "
        f"vertical={ds.attrs.get('vertical_coordinate')}"
    )

    if args.validate:
        result = validate_output(args.infile, output_path)
        if result["passed"]:
            print(
                "Validation: PASS "
                f"({result['variables_compared']} variables compared, "
                f"{result['checks_run']} checks)"
            )
        else:
            print("Validation: FAIL", file=sys.stderr)
            for issue in result["issues"]:
                print(f"  - {issue}", file=sys.stderr)
            raise SystemExit(2)


if __name__ == "__main__":
    main()
