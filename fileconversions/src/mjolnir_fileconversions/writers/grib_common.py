"""Shared grid, time, packing, layout and provenance support for GRIB writers."""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterable

import numpy as np

from ..errors import ConversionError, PressureEncodingError
from ..models import CanonicalDataset
from ..processing.time import DEFAULT_EPOCH, grib_valid_datetime


GRIB1_PARAMETERS = {
    "eastward_wind": (33, "m s-1"),
    "northward_wind": (34, "m s-1"),
    "omega": (39, "Pa s-1"),
}

GRIB2_PARAMETERS = {
    "eastward_wind": (0, 2, 2, "m s-1"),
    "northward_wind": (0, 2, 3, "m s-1"),
    "omega": (0, 2, 8, "Pa s-1"),
}


@dataclass(frozen=True)
class EncodedLevel:
    requested_pa: int
    effective_pa: int
    type_of_level: str
    encoded_level: int
    mode: str

    @property
    def absolute_error_pa(self) -> int:
        return abs(self.effective_pa - self.requested_pa)

    @property
    def relative_error(self) -> float:
        return self.absolute_error_pa / self.requested_pa


def eccodes_module():
    try:
        import eccodes
    except ImportError as exc:
        raise ConversionError(
            "Python eccodes is required. Install requirements-fileconversions.txt."
        ) from exc
    return eccodes


def encode_grib1_level(
    level_pa: float,
    mode: str = "strict",
    *,
    max_absolute_error_pa: float = 50.0,
    max_relative_error: float = 0.001,
) -> EncodedLevel:
    rounded_pa = int(round(level_pa))
    if not math.isclose(level_pa, rounded_pa, abs_tol=1e-8):
        raise PressureEncodingError(f"canonical pressure is not integer Pa: {level_pa}")
    if mode == "strict":
        if rounded_pa % 100:
            raise PressureEncodingError(
                f"{rounded_pa} Pa is not exactly representable by standard GRIB1 "
                "isobaricInhPa encoding; strict mode forbids silent hPa rounding"
            )
        hpa = rounded_pa // 100
        if not 0 <= hpa <= 65535:
            raise PressureEncodingError(f"{rounded_pa} Pa exceeds GRIB1 level storage")
        return EncodedLevel(rounded_pa, rounded_pa, "isobaricInhPa", hpa, mode)
    if mode == "hpa-rounded":
        hpa = int(round(rounded_pa / 100.0))
        effective = hpa * 100
        result = EncodedLevel(rounded_pa, effective, "isobaricInhPa", hpa, mode)
        if result.absolute_error_pa > max_absolute_error_pa or result.relative_error > max_relative_error:
            raise PressureEncodingError(
                f"hPa rounding {rounded_pa}->{effective} Pa exceeds limits "
                f"({max_absolute_error_pa} Pa, relative {max_relative_error})"
            )
        return result
    if mode == "ecmwf-pa":
        if not 0 <= rounded_pa <= 65535:
            raise PressureEncodingError(
                f"ecCodes GRIB1 isobaricInPa stores at most 65535 Pa, got {rounded_pa}"
            )
        return EncodedLevel(rounded_pa, rounded_pa, "isobaricInPa", rounded_pa, mode)
    raise PressureEncodingError(f"unknown GRIB1 level encoding mode: {mode}")


def set_regular_grid(codes, handle: int, latitude: np.ndarray, longitude: np.ndarray) -> None:
    latitude = np.asarray(latitude, dtype=np.float64)
    longitude = np.asarray(longitude, dtype=np.float64)
    if latitude[0] != -90.0 or latitude[-1] != 90.0:
        raise ConversionError("GRIB grid must include -90 and 90 degrees")
    if longitude[0] != 0.0 or longitude[-1] >= 360.0:
        raise ConversionError("GRIB longitude must be [0,360) without a duplicate 360")
    lat_step = float(np.diff(latitude)[0])
    lon_step = float(np.diff(longitude)[0])
    if not np.allclose(np.diff(latitude), lat_step, atol=1e-9, rtol=0):
        raise ConversionError("GRIB latitude is not regular")
    if not np.allclose(np.diff(longitude), lon_step, atol=1e-9, rtol=0):
        raise ConversionError("GRIB longitude is not regular")
    edition = int(codes.codes_get(handle, "edition"))
    if edition == 1 and max(lat_step, lon_step) * 1000 > 65535:
        raise ConversionError(
            "GRIB1 regular_ll stores direction increments in 16-bit millidegrees; "
            f"steps {lat_step}/{lon_step} exceed 65.535 degrees"
        )
    settings = {
        "gridType": "regular_ll",
        "Ni": int(longitude.size),
        "Nj": int(latitude.size),
        "latitudeOfFirstGridPointInDegrees": float(latitude[-1]),
        "longitudeOfFirstGridPointInDegrees": float(longitude[0]),
        "latitudeOfLastGridPointInDegrees": float(latitude[0]),
        "longitudeOfLastGridPointInDegrees": float(longitude[-1]),
        "iDirectionIncrementInDegrees": lon_step,
        "jDirectionIncrementInDegrees": lat_step,
        "iScansNegatively": 0,
        "jScansPositively": 0,
        "jPointsAreConsecutive": 0,
    }
    for key, value in settings.items():
        codes.codes_set(handle, key, value)
    # This scan flag is writable in the GRIB2 sample but derived/read-only in
    # ecCodes' GRIB1 sample. Both samples already use non-alternating rows.
    if edition == 2:
        codes.codes_set(handle, "alternativeRowScanning", 0)


def set_valid_time(codes, handle: int, valid: datetime) -> None:
    codes.codes_set(handle, "dataDate", int(valid.strftime("%Y%m%d")))
    codes.codes_set(handle, "dataTime", int(valid.strftime("%H%M")))
    codes.codes_set(handle, "stepUnits", "h")
    codes.codes_set(handle, "step", 0)


def set_values(codes, handle: int, values_south_to_north: np.ndarray, bits_per_value: int) -> None:
    values = np.asarray(values_south_to_north, dtype=np.float64)
    scan_values = values[::-1, :].reshape(-1)
    if np.any(np.isnan(scan_values)):
        # ecCodes uses the configured missingValue to construct a bitmap.
        # CODES_MISSING_DOUBLE works for the GRIB1 sample but overflows the
        # GRIB2 sample's IEEE conversion, so use an explicit finite sentinel.
        missing_sentinel = 1.0e36
        if np.any(scan_values[np.isfinite(scan_values)] == missing_sentinel):
            missing_sentinel = -1.0e36
        codes.codes_set(handle, "missingValue", missing_sentinel)
        codes.codes_set(handle, "bitmapPresent", 1)
        scan_values = np.where(np.isnan(scan_values), missing_sentinel, scan_values)
    codes.codes_set(handle, "packingType", "grid_simple")
    codes.codes_set(handle, "bitsPerValue", int(bits_per_value))
    codes.codes_set_values(handle, scan_values)


def valid_datetime(dataset: CanonicalDataset, time_index: int, epoch: str = DEFAULT_EPOCH) -> datetime:
    absolute = dataset.metadata.get("absolute_valid_times_utc")
    if absolute is not None:
        value = absolute[time_index]
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
        if parsed.second != 0 or parsed.microsecond != 0:
            raise ConversionError(
                "GRIB validity time has sub-minute precision and cannot be encoded exactly: "
                f"{parsed.isoformat()}"
            )
        return parsed
    return grib_valid_datetime(float(dataset.time_seconds[time_index]), epoch)


def layout_paths(
    dataset: CanonicalDataset,
    output_dir: Path,
    suffix: str,
    layout: str,
) -> dict[tuple[int, str], Path]:
    simulation = str(dataset.metadata.get("simulation_name", "mjolnir")).replace("/", "_")
    result: dict[tuple[int, str], Path] = {}
    if layout == "per-variable":
        for name in dataset.fields:
            path = output_dir / f"{simulation}_{name}.{suffix}"
            for time_index in range(dataset.time_seconds.size):
                result[(time_index, name)] = path
    elif layout == "per-time":
        for time_index in range(dataset.time_seconds.size):
            stamp = int(round(dataset.time_seconds[time_index]))
            path = output_dir / f"{simulation}_t{stamp:012d}.{suffix}"
            for name in dataset.fields:
                result[(time_index, name)] = path
    elif layout == "combined":
        path = output_dir / f"{simulation}_combined.{suffix}"
        for time_index in range(dataset.time_seconds.size):
            for name in dataset.fields:
                result[(time_index, name)] = path
    else:
        raise ConversionError(f"unknown file layout: {layout}")
    return result


def refuse_existing(paths: Iterable[Path], overwrite: bool) -> None:
    existing = sorted({path for path in paths if path.exists()})
    if existing and not overwrite:
        raise FileExistsError(
            "Refusing to overwrite existing output(s): " + ", ".join(map(str, existing))
        )


def git_commit() -> str:
    repository = Path(__file__).resolve().parents[4]
    try:
        return subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_sidecar(
    path: Path,
    dataset: CanonicalDataset,
    *,
    edition: int,
    level_encoding: str,
    technical_epoch: str = DEFAULT_EPOCH,
) -> None:
    parameter_metadata = {
        "eastward_wind": {
            "grib1_wire_id": "33.2",
            "grib2_id": "0/2/2",
            "eccodes_param_id": 131,
            "units": "m s-1",
        },
        "northward_wind": {
            "grib1_wire_id": "34.2",
            "grib2_id": "0/2/3",
            "eccodes_param_id": 132,
            "units": "m s-1",
        },
        "omega": {
            "grib1_wire_id": "39.2",
            "grib2_id": "0/2/8",
            "eccodes_param_id": 135,
            "units": "Pa s-1",
        },
    }
    payload = {
        "source_files": [str(item) for item in dataset.source_files],
        "simulation_name": dataset.metadata.get("simulation_name"),
        **dataset.planet.as_dict(),
        "source_grid": dataset.metadata.get("source_grid"),
        "target_grid": {
            "latitude": [float(dataset.latitude[0]), float(dataset.latitude[-1]), int(dataset.latitude.size)],
            "longitude": [float(dataset.longitude[0]), float(dataset.longitude[-1]), int(dataset.longitude.size)],
        },
        "pressure_levels_pa": dataset.level_pa.astype(int).tolist(),
        "pressure_level_policy": dataset.metadata.get("pressure_level_policy"),
        "vertical_interpolation_method": dataset.metadata.get(
            "vertical_interpolation_method"
        ),
        "vertical_interpolation_count": dataset.metadata.get(
            "vertical_interpolation_count"
        ),
        "grib_edition": edition,
        "grib1_level_encoding": level_encoding if edition == 1 else None,
        "omega_method": dataset.metadata.get("omega_method"),
        "time_reference": dataset.metadata.get("time_reference", DEFAULT_EPOCH),
        "elapsed_time_seconds": dataset.time_seconds.tolist(),
        "technical_epoch_utc": (
            None
            if dataset.metadata.get("absolute_valid_times_utc") is not None
            else technical_epoch
        ),
        "absolute_valid_times_utc": dataset.metadata.get("absolute_valid_times_utc"),
        "grib_parameters": {
            name: parameter_metadata[name] for name in dataset.fields
        },
        "software_version": "mjolnir-fileconversions 0.1.0",
        "git_commit": git_commit(),
        "review_status": "pending manual review by Márkó",
        "generated_with": "OpenAI Codex assistance",
    }
    sidecar = Path(str(path) + ".metadata.json")
    sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
