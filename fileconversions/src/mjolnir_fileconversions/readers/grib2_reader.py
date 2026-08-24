"""Message-by-message GRIB2 decoding with explicit metadata capture."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import numpy as np

from ..errors import ConversionError, UnsupportedMessageError


@dataclass
class Grib2Message:
    source_file: Path
    message_index: int
    field_name: str
    values: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    pressure_level_pa: int
    valid_datetime: datetime
    metadata: dict[str, object]


def _eccodes():
    try:
        import eccodes
    except ImportError as exc:
        raise ConversionError("Python eccodes is required for GRIB conversion") from exc
    return eccodes


def _get(codes, handle: int, key: str, default: object = None) -> object:
    try:
        return codes.codes_get(handle, key)
    except codes.CodesInternalError:
        return default


def _field_name(metadata: dict[str, object]) -> str:
    key = (
        int(metadata.get("discipline", -1)),
        int(metadata.get("parameterCategory", -1)),
        int(metadata.get("parameterNumber", -1)),
    )
    by_code = {(0, 2, 2): "eastward_wind", (0, 2, 3): "northward_wind", (0, 2, 8): "omega"}
    short = str(metadata.get("shortName", ""))
    if key in by_code:
        return by_code[key]
    if short in {"u", "10u"}:
        return "eastward_wind"
    if short in {"v", "10v"}:
        return "northward_wind"
    if short in {"w", "omega"} and "Pa" in str(metadata.get("units", "")):
        return "omega"
    raise UnsupportedMessageError(f"No GRIB1 mapping for GRIB2 parameter {key}, shortName={short!r}")


def iter_grib2(path: Path, *, on_unsupported: str = "error") -> Iterator[Grib2Message]:
    codes = _eccodes()
    path = path.expanduser().resolve()
    with path.open("rb") as stream:
        index = 0
        while True:
            handle = codes.codes_grib_new_from_file(stream)
            if handle is None:
                break
            index += 1
            try:
                edition = int(codes.codes_get(handle, "edition"))
                if edition != 2:
                    raise ConversionError(f"{path} message {index} is edition {edition}, not GRIB2")
                metadata = {
                    key: _get(codes, handle, key)
                    for key in (
                        "edition", "discipline", "parameterCategory", "parameterNumber",
                        "shortName", "name", "units", "typeOfLevel", "level",
                        "dataDate", "dataTime", "forecastTime", "stepUnits",
                        "gridType", "Ni", "Nj", "packingType", "missingValue",
                        "bitmapPresent", "centre", "subCentre", "tablesVersion",
                        "localTablesVersion",
                    )
                }
                try:
                    field_name = _field_name(metadata)
                except UnsupportedMessageError:
                    if on_unsupported == "skip":
                        field_name = ""
                    else:
                        raise
                if metadata["gridType"] != "regular_ll":
                    raise UnsupportedMessageError(f"Only regular_ll GRIB2 is supported, got {metadata['gridType']}")
                surface_units = str(_get(codes, handle, "unitsOfFirstFixedSurface", ""))
                scaled_surface = _get(codes, handle, "scaledValueOfFirstFixedSurface")
                scale_factor = _get(codes, handle, "scaleFactorOfFirstFixedSurface")
                if surface_units == "Pa" and scaled_surface is not None and scale_factor is not None:
                    pressure_pa = int(round(float(scaled_surface) * 10.0 ** (-int(scale_factor))))
                else:
                    units = str(_get(codes, handle, "pressureUnits", "hPa"))
                    level = float(metadata["level"])
                    pressure_pa = int(round(level if units == "Pa" else level * 100.0))
                lat_points = np.asarray(codes.codes_get_array(handle, "latitudes"), dtype=np.float64)
                lon_points = np.mod(np.asarray(codes.codes_get_array(handle, "longitudes"), dtype=np.float64), 360.0)
                raw = np.asarray(codes.codes_get_array(handle, "values"), dtype=np.float64)
                if int(metadata.get("bitmapPresent") or 0):
                    raw[
                        np.isclose(
                            raw,
                            codes.CODES_MISSING_DOUBLE,
                            rtol=1e-6,
                            atol=0,
                        )
                    ] = np.nan
                latitude = np.unique(np.round(lat_points, 10))
                longitude = np.unique(np.round(lon_points, 10))
                latitude.sort()
                longitude.sort()
                values = np.empty((latitude.size, longitude.size), dtype=np.float64)
                ilat = np.searchsorted(latitude, np.round(lat_points, 10))
                ilon = np.searchsorted(longitude, np.round(lon_points, 10))
                values[ilat, ilon] = raw
                date = int(metadata["dataDate"])
                time = int(metadata["dataTime"])
                valid_date = int(_get(codes, handle, "validityDate", date))
                valid_time = int(_get(codes, handle, "validityTime", time))
                valid = datetime(valid_date // 10000, valid_date // 100 % 100, valid_date % 100, valid_time // 100, valid_time % 100, tzinfo=timezone.utc)
                yield Grib2Message(path, index, field_name, values, latitude, longitude, pressure_pa, valid, metadata)
            finally:
                codes.codes_release(handle)
