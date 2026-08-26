"""ecCodes round-trip decoding and structural validation for both editions."""

from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np

from ..errors import ConversionError
from ..models import CanonicalDataset
from ..writers.grib_common import eccodes_module, valid_datetime
from .field_statistics import finite_statistics


@dataclass
class DecodedGribMessage:
    path: Path
    message_index: int
    edition: int
    field_name: str
    units: str
    pressure_level_pa: int
    valid_time: str
    latitude: np.ndarray
    longitude: np.ndarray
    values: np.ndarray
    metadata: dict[str, object]


def _get(codes, handle: int, key: str, default: object = None) -> object:
    try:
        return codes.codes_get(handle, key)
    except codes.CodesInternalError:
        return default


def _field(codes, handle: int, edition: int) -> str:
    if edition == 1:
        parameter = int(codes.codes_get(handle, "indicatorOfParameter"))
        table = int(codes.codes_get(handle, "table2Version"))
        mapping = {33: "eastward_wind", 34: "northward_wind", 39: "omega"}
        if table != 2 or parameter not in mapping:
            raise ConversionError(f"unsupported GRIB1 table/parameter {table}/{parameter}")
        return mapping[parameter]
    key = (
        int(codes.codes_get(handle, "discipline")),
        int(codes.codes_get(handle, "parameterCategory")),
        int(codes.codes_get(handle, "parameterNumber")),
    )
    mapping = {(0, 2, 2): "eastward_wind", (0, 2, 3): "northward_wind", (0, 2, 8): "omega"}
    if key not in mapping:
        raise ConversionError(f"unsupported GRIB2 parameter {key}")
    return mapping[key]


def decode_grib_messages(paths: Sequence[Path]) -> list[DecodedGribMessage]:
    codes = eccodes_module()
    result: list[DecodedGribMessage] = []
    for path in sorted(path.expanduser().resolve() for path in paths):
        with path.open("rb") as stream:
            index = 0
            while True:
                handle = codes.codes_grib_new_from_file(stream)
                if handle is None:
                    break
                index += 1
                try:
                    edition = int(codes.codes_get(handle, "edition"))
                    field_name = _field(codes, handle, edition)
                    if edition == 2 and str(_get(codes, handle, "unitsOfFirstFixedSurface", "")) == "Pa":
                        scaled = float(codes.codes_get(handle, "scaledValueOfFirstFixedSurface"))
                        factor = int(codes.codes_get(handle, "scaleFactorOfFirstFixedSurface"))
                        level_pa = int(round(scaled * 10.0 ** (-factor)))
                    else:
                        pressure_units = str(_get(codes, handle, "pressureUnits", "hPa"))
                        raw_level = float(codes.codes_get(handle, "level"))
                        level_pa = int(round(raw_level if pressure_units == "Pa" else raw_level * 100.0))
                    lat_points = np.asarray(codes.codes_get_array(handle, "latitudes"), dtype=np.float64)
                    lon_points = np.mod(np.asarray(codes.codes_get_array(handle, "longitudes"), dtype=np.float64), 360.0)
                    raw_values = np.asarray(codes.codes_get_array(handle, "values"), dtype=np.float64)
                    if int(_get(codes, handle, "bitmapPresent", 0)):
                        bitmap = np.asarray(
                            codes.codes_get_array(handle, "bitmap"), dtype=np.int8
                        )
                        if bitmap.shape != raw_values.shape:
                            raise ConversionError(
                                f"{path} message {index} bitmap/value shape mismatch"
                            )
                        raw_values[bitmap == 0] = np.nan
                    latitude = np.unique(np.round(lat_points, 10)); latitude.sort()
                    longitude = np.unique(np.round(lon_points, 10)); longitude.sort()
                    values = np.empty((latitude.size, longitude.size), dtype=np.float64)
                    values[
                        np.searchsorted(latitude, np.round(lat_points, 10)),
                        np.searchsorted(longitude, np.round(lon_points, 10)),
                    ] = raw_values
                    valid_date = int(_get(codes, handle, "validityDate", codes.codes_get(handle, "dataDate")))
                    valid_time = int(_get(codes, handle, "validityTime", codes.codes_get(handle, "dataTime")))
                    valid = f"{valid_date:08d}T{valid_time:04d}"
                    metadata = {
                        key: _get(codes, handle, key)
                        for key in (
                            "gridType", "Ni", "Nj", "iScansNegatively", "jScansPositively",
                            "packingType", "bitsPerValue", "bitmapPresent", "centre", "subCentre",
                            "table2Version", "indicatorOfParameter", "discipline", "parameterCategory",
                            "parameterNumber", "typeOfLevel", "level", "pressureUnits", "shortName",
                            "name", "units",
                        )
                    }
                    result.append(
                        DecodedGribMessage(path, index, edition, field_name, "Pa s-1" if field_name == "omega" else "m s-1", level_pa, valid, latitude, longitude, values, metadata)
                    )
                finally:
                    codes.codes_release(handle)
    if not result:
        raise ConversionError("No GRIB messages decoded")
    return result


def validate_grib_files(paths: Sequence[Path], *, expected_edition: int | None = None) -> tuple[list[dict[str, object]], list[str]]:
    messages = decode_grib_messages(paths)
    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    for item in messages:
        errors: list[str] = []
        if expected_edition is not None and item.edition != expected_edition:
            errors.append(f"edition {item.edition} != {expected_edition}")
        if item.metadata.get("gridType") != "regular_ll":
            errors.append("grid is not regular_ll")
        lat_d = np.diff(item.latitude)
        lon_d = np.diff(item.longitude)
        if item.latitude[0] != -90.0 or item.latitude[-1] != 90.0:
            errors.append("exact poles are absent")
        if not (np.all(lat_d > 0) and np.allclose(lat_d, lat_d[0], atol=1e-8, rtol=0)):
            errors.append("latitude is not regular/increasing")
        periodic = lon_d.size and np.allclose(lon_d, lon_d[0], atol=1e-8, rtol=0) and math.isclose(item.longitude[-1] + lon_d[0] - item.longitude[0], 360.0, abs_tol=1e-8)
        if not periodic or np.any(item.longitude == 360.0):
            errors.append("longitude is not periodic [0,360)")
        if np.any(np.isinf(item.values)):
            errors.append("field contains Inf")
        if item.field_name == "omega" and item.units != "Pa s-1":
            errors.append("omega unit is not Pa s-1")
        stat = finite_statistics(item.values)
        rows.append(
            {
                "input_file": str(item.path),
                "message_index": item.message_index,
                "edition": item.edition,
                "variable": item.field_name,
                "time": item.valid_time,
                "pressure_level_pa": item.pressure_level_pa,
                "grid": f"{item.latitude.size}x{item.longitude.size}",
                **stat,
                "status": "passed" if not errors else "failed",
                "warnings": "; ".join(errors),
            }
        )
    if shutil.which("cdo"):
        for path in paths:
            process = subprocess.run(["cdo", "-s", "sinfo", str(path)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if process.returncode:
                warnings.append(f"CDO could not reopen {path}: {process.stdout[-300:]}")
    else:
        warnings.append("CDO is unavailable")
    for command in ("grib_ls", "grib_dump", "wgrib", "wgrib2"):
        if shutil.which(command) is None:
            warnings.append(f"optional external validator unavailable: {command}")
    return rows, warnings


def roundtrip_against_canonical(
    paths: Sequence[Path],
    dataset: CanonicalDataset,
    *,
    technical_epoch: str,
    conversion_mode: str,
    packing_tolerance: float = 1e-4,
) -> list[dict[str, object]]:
    """Compare decoded GRIB values directly with the writer input arrays."""
    decoded_messages = decode_grib_messages(paths)
    decoded = {
        (item.field_name, item.valid_time, item.pressure_level_pa): item
        for item in decoded_messages
    }
    by_field_time: dict[tuple[str, str], list[DecodedGribMessage]] = {}
    for item in decoded_messages:
        by_field_time.setdefault((item.field_name, item.valid_time), []).append(item)
    for values in by_field_time.values():
        values.sort(key=lambda item: (str(item.path), item.message_index))
    rows: list[dict[str, object]] = []
    for time_index in range(dataset.time_seconds.size):
        stamp = valid_datetime(dataset, time_index, technical_epoch).strftime("%Y%m%dT%H%M")
        for field_name, field in dataset.fields.items():
            for level_index, level in enumerate(dataset.level_pa):
                key = (field_name, stamp, int(round(level)))
                item = decoded.get(key)
                if item is None:
                    candidates = by_field_time.get((field_name, stamp), [])
                    if len(candidates) != dataset.level_pa.size:
                        raise ConversionError(f"round-trip output is missing message {key}")
                    item = candidates[level_index]
                expected = field[time_index, level_index]
                if expected.shape != item.values.shape:
                    raise ConversionError(
                        f"round-trip grid mismatch for {key}: {expected.shape} vs {item.values.shape}"
                    )
                expected_missing = ~np.isfinite(expected)
                decoded_missing = ~np.isfinite(item.values)
                missing_mismatch = int(np.count_nonzero(expected_missing != decoded_missing))
                finite = ~expected_missing & ~decoded_missing
                difference = item.values[finite] - expected[finite]
                if difference.size:
                    max_abs = float(np.max(np.abs(difference)))
                    rms = float(np.sqrt(np.mean(np.square(difference))))
                else:
                    max_abs = float("nan")
                    rms = float("nan")
                stat = finite_statistics(item.values)
                rows.append(
                    {
                        "input_file": ";".join(map(str, dataset.source_files)),
                        "output_file": str(item.path),
                        "edition": item.edition,
                        "variable": field_name,
                        "time": stamp,
                        "pressure_level_pa": int(round(level)),
                        "encoded_pressure_level_pa": item.pressure_level_pa,
                        "grid": f"{item.latitude.size}x{item.longitude.size}",
                        "conversion_mode": conversion_mode,
                        "omega_mode": dataset.metadata.get("omega_method", "not applicable"),
                        **stat,
                        "round_trip_maximum_absolute_error": max_abs,
                        "round_trip_rms_error": rms,
                        "missing_mask_mismatch_count": missing_mismatch,
                        "packing_tolerance": packing_tolerance,
                        "status": (
                            "passed"
                            if missing_mismatch == 0 and max_abs <= packing_tolerance
                            else "failed"
                        ),
                        "warnings": "",
                    }
                )
    if len(decoded_messages) != len(rows):
        raise ConversionError(
            f"round-trip message count differs: decoded {len(decoded_messages)}, expected {len(rows)}"
        )
    return rows
