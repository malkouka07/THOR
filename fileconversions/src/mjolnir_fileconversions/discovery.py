"""Input discovery and strict HDF5 structural classification."""

from __future__ import annotations

import csv
import glob
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import h5py
import numpy as np

from .errors import InputClassificationError


HDF5_SUFFIXES = {".h5", ".hdf5"}


@dataclass(frozen=True)
class HDF5Classification:
    file_path: str
    file_name: str
    file_size: int
    classification: str
    classification_confidence: str
    grid_type: str
    has_latitude: bool
    has_longitude: bool
    has_pressure_levels: bool
    has_time: bool
    main_variables: str
    reason: str
    selected_for_conversion: bool = False

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def _regular_1d(handle: h5py.File, name: str) -> bool:
    if name not in handle or handle[name].ndim != 1 or handle[name].size < 2:
        return False
    values = np.asarray(handle[name][...], dtype=np.float64)
    return bool(
        np.all(np.isfinite(values))
        and np.all(np.diff(values) > 0)
        and np.allclose(np.diff(values), np.diff(values)[0], atol=1e-8, rtol=0)
    )


def classify_hdf5(path: Path) -> HDF5Classification:
    """Classify a file from structure; a filename is evidence, not the decision."""
    path = path.expanduser().resolve()
    base = dict(file_path=str(path), file_name=path.name, file_size=path.stat().st_size)
    try:
        with h5py.File(path, "r") as handle:
            keys = set(handle.keys())
            has_lat = "Latitude" in keys or "latitude" in keys
            has_lon = "Longitude" in keys or "longitude" in keys
            lat_name = "Latitude" if "Latitude" in keys else "latitude"
            lon_name = "Longitude" if "Longitude" in keys else "longitude"
            regular = (
                has_lat
                and has_lon
                and _regular_1d(handle, lat_name)
                and _regular_1d(handle, lon_name)
            )
            wind_names = [name for name in ("U", "V", "W", "U_mean", "V_mean", "W_mean") if name in keys]
            canonical_winds = [
                name
                for name in ("eastward_wind", "northward_wind", "omega")
                if name in keys
            ]
            has_pressure = bool(
                keys.intersection({"Pressure", "Pressure_mean", "pressure", "level", "plev"})
                or {"Rho", "Rd", "Temperature"}.issubset(keys)
            )
            has_time = bool(keys.intersection({"simulation_time", "time", "Time"}))
            if regular and (
                {"U", "V"}.issubset(keys)
                or {"U_mean", "V_mean"}.issubset(keys)
                or {"eastward_wind", "northward_wind"}.issubset(keys)
            ):
                classification = "mjolnir_processed"
                confidence = "high"
                grid_type = "regular_latitude_longitude"
                reason = (
                    "Independent 1-D regular Latitude/Longitude coordinates and "
                    "3-D geographic wind fields match Mjolnir regrid products."
                )
            elif "Mh" in keys and "Wh" in keys and not (has_lat and has_lon):
                classification = "native_icosahedral"
                confidence = "high"
                grid_type = "native_icosahedral"
                reason = (
                    "Flattened Mh/Wh momentum fields are present and independent "
                    "regular Latitude/Longitude coordinates are absent."
                )
            elif keys.intersection({"lonlat", "point_xyz", "maps", "A", "Gravit"}):
                classification = "metadata_or_grid"
                confidence = "high"
                grid_type = "metadata_or_grid"
                reason = "Grid topology or scalar planet metadata is present without data winds."
            else:
                classification = "unknown"
                confidence = "low"
                grid_type = "unknown"
                reason = "Structure does not match a supported processed, native, or metadata product."
            return HDF5Classification(
                **base,
                classification=classification,
                classification_confidence=confidence,
                grid_type=grid_type,
                has_latitude=has_lat,
                has_longitude=has_lon,
                has_pressure_levels=has_pressure,
                has_time=has_time,
                main_variables=";".join(wind_names + canonical_winds),
                reason=reason,
            )
    except Exception as exc:
        return HDF5Classification(
            **base,
            classification="unknown",
            classification_confidence="low",
            grid_type="unknown",
            has_latitude=False,
            has_longitude=False,
            has_pressure_levels=False,
            has_time=False,
            main_variables="",
            reason=f"HDF5 inspection failed: {exc}",
        )


def discover_paths(
    inputs: Sequence[Path] | None,
    input_dir: Path | None,
    input_glob: str | None,
    suffixes: set[str],
) -> list[Path]:
    """Resolve explicit inputs, a directory, and a glob deterministically."""
    paths: list[Path] = []
    if inputs:
        paths.extend(path.expanduser().resolve() for path in inputs)
    if input_dir:
        root = input_dir.expanduser().resolve()
        pattern = input_glob or "*"
        paths.extend(path.resolve() for path in root.glob(pattern) if path.is_file())
    elif input_glob:
        paths.extend(Path(item).resolve() for item in glob.glob(input_glob))
    unique = sorted({path for path in paths if path.suffix.lower() in suffixes})
    if not unique:
        raise FileNotFoundError("No matching input files were found")
    missing = [path for path in unique if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Input files do not exist: {missing}")
    return unique


def classify_collection(paths: Iterable[Path]) -> list[HDF5Classification]:
    return [classify_hdf5(path) for path in paths]


def require_processed(paths: Sequence[Path]) -> list[HDF5Classification]:
    results = classify_collection(paths)
    rejected = [item for item in results if item.classification != "mjolnir_processed"]
    if rejected:
        detail = "\n".join(
            f"- {item.file_path}: {item.classification} ({item.reason})"
            for item in results
        )
        raise InputClassificationError(
            "Only Mjolnir-processed HDF5 is accepted; native THOR output is never "
            f"used as a production input. Classification:\n{detail}"
        )
    return [
        HDF5Classification(**{**item.as_dict(), "selected_for_conversion": True})
        for item in results
    ]


def write_classification_csv(path: Path, rows: Sequence[HDF5Classification]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(HDF5Classification.__dataclass_fields__)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(row.as_dict() for row in rows)
