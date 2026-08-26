"""Message-by-message GRIB2 decoding with explicit metadata capture."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

import numpy as np

from ..errors import ConversionError, UnsupportedMessageError
from ..models import CanonicalDataset, PlanetParameters, ProcessingStage
from ..processing.pressure import (
    PressureMapping,
    derive_hpa_aligned_levels,
    derive_integer_levels,
    interpolate_log_pressure,
)


@dataclass
class Grib2Message:
    source_file: Path
    message_index: int
    field_name: str
    values: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    pressure_level_pa: int | None
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


def _sidecar_provenance(
    paths: Sequence[Path],
) -> tuple[PlanetParameters, str, str | None]:
    """Reuse provenance only when every source has one consistent sidecar."""
    payloads: list[dict[str, object]] = []
    for path in paths:
        sidecar = Path(str(Path(path).expanduser().resolve()) + ".metadata.json")
        if not sidecar.is_file():
            return PlanetParameters(name="unknown"), "grib2_conversion", None
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return PlanetParameters(name="unknown"), "grib2_conversion", None
        if not isinstance(payload, dict):
            return PlanetParameters(name="unknown"), "grib2_conversion", None
        payloads.append(payload)

    keys = (
        "planet",
        "radius_m",
        "gravity_m_s2",
        "rotation_rate_s1",
        "gas_constant_j_kg_k",
        "heat_capacity_j_kg_k",
        "reference_pressure_pa",
        "source",
        "simulation_name",
        "omega_method",
    )
    first = payloads[0]
    for payload in payloads[1:]:
        if any(payload.get(key) != first.get(key) for key in keys):
            raise ConversionError("GRIB2 source sidecars contain conflicting provenance")

    def numeric(key: str) -> float | None:
        value = first.get(key)
        return float(value) if value is not None else None

    planet = PlanetParameters(
        name=str(first.get("planet") or "unknown"),
        radius_m=numeric("radius_m"),
        gravity_m_s2=numeric("gravity_m_s2"),
        rotation_rate_s1=numeric("rotation_rate_s1"),
        gas_constant_j_kg_k=numeric("gas_constant_j_kg_k"),
        heat_capacity_j_kg_k=numeric("heat_capacity_j_kg_k"),
        reference_pressure_pa=numeric("reference_pressure_pa"),
        source=str(first["source"]) if first.get("source") else None,
    )
    return (
        planet,
        str(first.get("simulation_name") or "grib2_conversion"),
        str(first["omega_method"]) if first.get("omega_method") else None,
    )


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
                        "second",
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
                is_pressure_surface = metadata["typeOfLevel"] in {
                    "isobaricInPa",
                    "isobaricInhPa",
                }
                if not is_pressure_surface:
                    message = (
                        "Only isobaric GRIB2 surfaces are supported, got "
                        f"{metadata['typeOfLevel']!r}"
                    )
                    if on_unsupported == "skip":
                        field_name = ""
                        pressure_pa = None
                    else:
                        raise UnsupportedMessageError(message)
                else:
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
                    bitmap = np.asarray(
                        codes.codes_get_array(handle, "bitmap"), dtype=np.int8
                    )
                    if bitmap.shape != raw.shape:
                        raise ConversionError(
                            f"{path} message {index} bitmap/value shape mismatch"
                        )
                    raw[bitmap == 0] = np.nan
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
                second = int(_get(codes, handle, "second", 0) or 0)
                if second != 0:
                    raise ConversionError(
                        "GRIB2 validity time has sub-minute precision and cannot be "
                        f"preserved in GRIB1: second={second}"
                    )
                valid = datetime(valid_date // 10000, valid_date // 100 % 100, valid_date % 100, valid_time // 100, valid_time % 100, tzinfo=timezone.utc)
                yield Grib2Message(path, index, field_name, values, latitude, longitude, pressure_pa, valid, metadata)
            finally:
                codes.codes_release(handle)


def read_grib2_collection(
    paths: Sequence[Path],
    *,
    on_unsupported: str = "error",
    time_indices: Sequence[int] | None = None,
    pressure_level_policy: str = "hpa-aligned",
) -> tuple[CanonicalDataset, list[PressureMapping], list[Grib2Message]]:
    """Assemble complete pressure stacks before any GRIB1 conversion.

    GRIB messages are unordered records, so vertical interpolation is only
    scientifically defined after grouping by valid time and parameter.  This
    adapter rejects duplicate/incomplete stacks and differing grids rather
    than silently mixing them.
    """
    if not paths:
        raise ConversionError("empty GRIB2 collection")
    source_planet, simulation_name, source_omega_method = _sidecar_provenance(paths)
    messages = [
        message
        for path in paths
        for message in iter_grib2(path, on_unsupported=on_unsupported)
    ]
    supported = [message for message in messages if message.field_name]
    if not supported:
        raise ConversionError("GRIB2 collection contains no supported pressure-level fields")

    all_times = sorted({message.valid_datetime for message in supported})
    if time_indices is None:
        selected_times = all_times
    else:
        indices = np.asarray(time_indices, dtype=int)
        if indices.size == 0:
            raise ConversionError("--time-indices cannot be empty")
        if np.any(indices < 0) or np.any(indices >= len(all_times)):
            raise ConversionError(
                f"GRIB2 time index outside 0..{len(all_times) - 1}: {indices.tolist()}"
            )
        if len(np.unique(indices)) != indices.size:
            raise ConversionError("duplicate GRIB2 time indices")
        selected_times = sorted(all_times[index] for index in indices)
    selected_set = set(selected_times)
    selected = [message for message in supported if message.valid_datetime in selected_set]

    first = selected[0]
    for message in selected[1:]:
        if (
            message.latitude.shape != first.latitude.shape
            or message.longitude.shape != first.longitude.shape
            or not np.allclose(message.latitude, first.latitude, atol=1e-10, rtol=0)
            or not np.allclose(message.longitude, first.longitude, atol=1e-10, rtol=0)
        ):
            raise ConversionError(
                "GRIB2 collection grids differ; pressure stacks cannot be combined"
            )

    field_order = ("eastward_wind", "northward_wind", "omega")
    fields = [name for name in field_order if any(item.field_name == name for item in selected)]
    groups: dict[tuple[datetime, str], dict[int, Grib2Message]] = {}
    for message in selected:
        assert message.pressure_level_pa is not None
        key = (message.valid_datetime, message.field_name)
        level_messages = groups.setdefault(key, {})
        if message.pressure_level_pa in level_messages:
            previous = level_messages[message.pressure_level_pa]
            raise ConversionError(
                "duplicate GRIB2 pressure message for "
                f"{message.valid_datetime.isoformat()} {message.field_name} "
                f"{message.pressure_level_pa} Pa: {previous.source_file} and {message.source_file}"
            )
        level_messages[message.pressure_level_pa] = message

    expected_keys = {(valid, field) for valid in selected_times for field in fields}
    missing_groups = expected_keys - set(groups)
    if missing_groups:
        preview = ", ".join(
            f"{valid.isoformat()}:{field}" for valid, field in sorted(missing_groups)[:5]
        )
        raise ConversionError(f"incomplete GRIB2 time/field collection; missing {preview}")

    reference_levels: np.ndarray | None = None
    for key in sorted(groups):
        group_levels = np.asarray(sorted(groups[key], reverse=True), dtype=np.int64)
        if reference_levels is None:
            reference_levels = group_levels
        elif not np.array_equal(group_levels, reference_levels):
            raise ConversionError(
                "GRIB2 pressure stacks differ between time/field groups; "
                "automatic interpolation requires one common source level set"
            )
    assert reference_levels is not None
    if np.any(reference_levels <= 0):
        raise ConversionError("GRIB2 pressure levels must be positive")

    if pressure_level_policy == "hpa-aligned":
        target_levels, mapping = derive_hpa_aligned_levels(reference_levels)
    elif pressure_level_policy == "source":
        target_levels, mapping = derive_integer_levels(reference_levels)
    else:
        raise ConversionError(
            f"unsupported pressure-level policy: {pressure_level_policy}"
        )

    canonical_fields: dict[str, np.ndarray] = {}
    for field in fields:
        time_stacks: list[np.ndarray] = []
        for valid in selected_times:
            by_level = groups[(valid, field)]
            source_stack = np.stack(
                [by_level[int(level)].values for level in reference_levels], axis=0
            )
            # interpolate_log_pressure expects pressure on the last axis.
            lat_lon_level = source_stack.transpose(1, 2, 0)
            if np.array_equal(reference_levels, target_levels):
                converted = lat_lon_level.copy()
            else:
                converted = interpolate_log_pressure(
                    lat_lon_level, reference_levels, target_levels
                )
            time_stacks.append(converted.transpose(2, 0, 1))
        canonical_fields[field] = np.stack(time_stacks, axis=0)

    first_valid = selected_times[0]
    elapsed = np.asarray(
        [(valid - first_valid).total_seconds() for valid in selected_times],
        dtype=np.float64,
    )
    units = {
        name: "Pa s-1" if name == "omega" else "m s-1" for name in fields
    }
    stage_pairs = sorted(
        {(message.source_file, message.field_name) for message in selected},
        key=lambda item: (str(item[0]), item[1]),
    )
    stages = [
        ProcessingStage(
            input_file=str(path),
            field=field,
            detected_grid_stage="GRIB2 regular_ll",
            detected_vector_stage="GRIB2 geographic component",
            detected_vertical_stage="GRIB2 pressure levels",
            detected_units=units[field],
            required_next_step=(
                "log-pressure interpolation to exact integer-hPa surfaces and GRIB1 encoding"
                if pressure_level_policy == "hpa-aligned"
                else "GRIB1 encoding"
            ),
            skipped_as_already_completed="horizontal remapping and physical variable derivation",
            evidence="decoded GRIB2 parameter, grid and fixed-surface metadata",
        )
        for path, field in stage_pairs
    ]
    dataset = CanonicalDataset(
        time_seconds=elapsed,
        level_pa=target_levels,
        latitude=first.latitude,
        longitude=first.longitude,
        fields=canonical_fields,
        units=units,
        source_files=[Path(path).expanduser().resolve() for path in paths],
        planet=source_planet,
        metadata={
            "simulation_name": simulation_name,
            "source_kind": "grib2",
            "pressure_level_policy": pressure_level_policy,
            "vertical_interpolation_method": (
                "piecewise linear in log(p)" if any(
                    item.interpolation_performed for item in mapping
                ) else "none"
            ),
            "vertical_interpolation_count": int(
                any(item.interpolation_performed for item in mapping)
            ),
            "omega_method": (
                "native pressure omega decoded from GRIB2"
                + (
                    f"; source provenance: {source_omega_method}"
                    if source_omega_method
                    else ""
                )
                if "omega" in fields
                else "not present"
            ),
            "absolute_valid_times_utc": [
                valid.isoformat().replace("+00:00", "Z") for valid in selected_times
            ],
            "time_reference": "native GRIB2 validity datetimes retained exactly",
            "source_count": len(paths),
            "review_status": "pending manual review by Márkó",
        },
        stages=stages,
    )
    return dataset, mapping, messages
