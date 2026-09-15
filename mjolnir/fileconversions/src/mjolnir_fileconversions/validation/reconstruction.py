"""Reconstruct decoded GRIB fields on their original HDF5 coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import xarray as xr

from ..errors import ConversionError
from ..models import SourceReferenceDataset
from ..processing.grid import periodic_bilinear_interpolate
from ..processing.time import grib_valid_datetime
from .grib_validation import DecodedGribMessage, decode_grib_messages


@dataclass
class ReconstructionResult:
    """Numerical fields and tabular statistics from one reconstruction."""

    rows: list[dict[str, object]]
    reconstructed: dict[str, np.ndarray]
    decoded_levels_pa: dict[tuple[int, str], np.ndarray]


def _decoded_groups(
    messages: Sequence[DecodedGribMessage],
) -> dict[tuple[str, str], list[DecodedGribMessage]]:
    groups: dict[tuple[str, str], list[DecodedGribMessage]] = {}
    seen: set[tuple[str, str, int]] = set()
    for message in messages:
        key = (message.field_name, message.valid_time, message.pressure_level_pa)
        if key in seen:
            raise ConversionError(f"duplicate decoded GRIB reconstruction key: {key}")
        seen.add(key)
        groups.setdefault((message.field_name, message.valid_time), []).append(message)
    for key, stack in groups.items():
        stack.sort(key=lambda item: item.pressure_level_pa)
        levels = np.asarray([item.pressure_level_pa for item in stack])
        if levels.size == 0 or np.any(np.diff(levels) <= 0):
            raise ConversionError(
                f"decoded reconstruction stack {key} needs distinct pressure levels"
            )
        first = stack[0]
        for item in stack[1:]:
            if (
                item.latitude.shape != first.latitude.shape
                or item.longitude.shape != first.longitude.shape
                or not np.allclose(item.latitude, first.latitude, atol=1e-10, rtol=0)
                or not np.allclose(item.longitude, first.longitude, atol=1e-10, rtol=0)
            ):
                raise ConversionError(f"decoded reconstruction grids differ for {key}")
    return groups


def _vertical_reconstruct(
    values_at_source_horizontal_grid: np.ndarray,
    decoded_pressure_pa: np.ndarray,
    source_pressure_pa: np.ndarray,
) -> np.ndarray:
    """Interpolate decoded isobars to local source pressures without extrapolation."""
    values = np.asarray(values_at_source_horizontal_grid, dtype=np.float64)
    levels = np.asarray(decoded_pressure_pa, dtype=np.float64)
    source_pressure = np.asarray(source_pressure_pa, dtype=np.float64)
    if values.shape[:2] != source_pressure.shape[1:]:
        raise ConversionError("reconstruction horizontal/source pressure grid mismatch")
    if values.shape[2] != levels.size:
        raise ConversionError("reconstruction pressure/value stack mismatch")
    if np.any(np.diff(levels) <= 0):
        raise ConversionError("decoded reconstruction pressure must be ascending")

    output = np.full(source_pressure.shape, np.nan, dtype=np.float64)
    log_levels = np.log(levels)
    minimum = levels[0]
    maximum = levels[-1]
    for y_index in range(source_pressure.shape[1]):
        for x_index in range(source_pressure.shape[2]):
            column = values[y_index, x_index]
            targets = source_pressure[:, y_index, x_index]
            in_range = (targets >= minimum - 1e-8) & (targets <= maximum + 1e-8)
            for level_index in np.flatnonzero(in_range):
                target = float(targets[level_index])
                insertion = int(np.searchsorted(levels, target))
                if insertion < levels.size and np.isclose(
                    levels[insertion], target, atol=1e-8, rtol=0
                ):
                    value = column[insertion]
                elif insertion > 0 and np.isclose(
                    levels[insertion - 1], target, atol=1e-8, rtol=0
                ):
                    value = column[insertion - 1]
                elif insertion == 0 or insertion == levels.size:
                    continue
                else:
                    lower = insertion - 1
                    upper = insertion
                    if not (
                        np.isfinite(column[lower]) and np.isfinite(column[upper])
                    ):
                        continue
                    weight = (
                        np.log(target) - log_levels[lower]
                    ) / (log_levels[upper] - log_levels[lower])
                    value = column[lower] + weight * (
                        column[upper] - column[lower]
                    )
                if np.isfinite(value):
                    output[level_index, y_index, x_index] = value
    return output


def _regions(
    source_latitude: np.ndarray, decoded_latitude: np.ndarray
) -> list[tuple[str, np.ndarray]]:
    south = source_latitude < decoded_latitude[1] - 1e-10
    north = source_latitude > decoded_latitude[-2] + 1e-10
    interior = ~(south | north)
    return [
        ("all", np.ones(source_latitude.size, dtype=bool)),
        ("interior", interior),
        ("south_pole_influenced", south),
        ("north_pole_influenced", north),
    ]


def _statistics_row(
    *,
    source: SourceReferenceDataset,
    field_name: str,
    time_index: int,
    stamp: str,
    level_index: int,
    region_name: str,
    latitude_mask: np.ndarray,
    original: np.ndarray,
    reconstructed: np.ndarray,
    source_pressure: np.ndarray,
    decoded_levels: np.ndarray,
) -> dict[str, object]:
    region = np.broadcast_to(latitude_mask[:, None], original.shape)
    pressure_in_range = (
        (source_pressure >= decoded_levels[0] - 1e-8)
        & (source_pressure <= decoded_levels[-1] + 1e-8)
        & region
    )
    comparable = pressure_in_range & np.isfinite(original) & np.isfinite(reconstructed)
    difference = reconstructed[comparable] - original[comparable]
    count = int(difference.size)
    absolute = np.abs(difference)
    source_values = original[comparable]
    reference_absolute = np.abs(source_values)
    reconstructed_values = reconstructed[comparable]
    if count:
        maximum_absolute = float(np.max(absolute))
        mean_absolute = float(np.mean(absolute))
        reference_maximum_absolute = float(np.max(reference_absolute))
        reference_mean_absolute = float(np.mean(reference_absolute))
        rms = float(np.sqrt(np.mean(np.square(difference))))
        bias = float(np.mean(difference))
        source_rms = float(np.sqrt(np.mean(np.square(source_values))))
        relative_rms = rms / max(source_rms, 1e-30)
        if count > 1 and np.std(source_values) > 0 and np.std(reconstructed_values) > 0:
            correlation = float(np.corrcoef(source_values, reconstructed_values)[0, 1])
        else:
            correlation = float("nan")
        latitude_weights = np.cos(np.deg2rad(source.latitude))[:, None]
        weights = np.broadcast_to(latitude_weights, original.shape)[comparable]
        weight_sum = float(np.sum(weights))
        area_mean_absolute = float(np.sum(weights * absolute) / weight_sum)
        area_rms = float(np.sqrt(np.sum(weights * np.square(difference)) / weight_sum))
        area_bias = float(np.sum(weights * difference) / weight_sum)
        original_min = float(np.min(source_values))
        original_max = float(np.max(source_values))
        reconstructed_min = float(np.min(reconstructed_values))
        reconstructed_max = float(np.max(reconstructed_values))
        status = "measured"
        reason = ""
    else:
        maximum_absolute = mean_absolute = rms = bias = float("nan")
        reference_maximum_absolute = reference_mean_absolute = float("nan")
        relative_rms = correlation = float("nan")
        area_mean_absolute = area_rms = area_bias = float("nan")
        original_min = original_max = float("nan")
        reconstructed_min = reconstructed_max = float("nan")
        status = "not_comparable"
        reason = (
            "source pressure is outside the decoded GRIB pressure range"
            if not np.any(pressure_in_range)
            else "no finite original/reconstructed pairs"
        )
    pressure_values = source_pressure[region]
    return {
        "row_type": "detail",
        "comparison_stage": "decoded_grib1_back_on_original_hdf5_grid",
        "variable": field_name,
        "units": source.units[field_name],
        "time": stamp,
        "elapsed_time_seconds": float(source.time_seconds[time_index]),
        "source_file": str(source.source_files[time_index]),
        "source_dataset": source.source_dataset_names.get(field_name, ""),
        "source_level_index": level_index,
        "source_pressure_mean_pa": float(np.mean(pressure_values)),
        "source_pressure_min_pa": float(np.min(pressure_values)),
        "source_pressure_max_pa": float(np.max(pressure_values)),
        "decoded_pressure_min_pa": int(decoded_levels[0]),
        "decoded_pressure_max_pa": int(decoded_levels[-1]),
        "region": region_name,
        "total_value_count": int(np.count_nonzero(region)),
        "pressure_in_range_count": int(np.count_nonzero(pressure_in_range)),
        "compared_value_count": count,
        "excluded_pressure_count": int(np.count_nonzero(region & ~pressure_in_range)),
        "missing_or_unreconstructed_count": int(
            np.count_nonzero(pressure_in_range & ~comparable)
        ),
        "original_minimum": original_min,
        "original_maximum": original_max,
        "reconstructed_minimum": reconstructed_min,
        "reconstructed_maximum": reconstructed_max,
        "maximum_absolute_difference": maximum_absolute,
        "mean_absolute_difference": mean_absolute,
        "reference_maximum_absolute_value": reference_maximum_absolute,
        "reference_mean_absolute_value": reference_mean_absolute,
        "reference_absolute_value_sum": float(np.sum(reference_absolute)),
        "absolute_difference_sum": float(np.sum(absolute)),
        "percentage_reference": "original_hdf5",
        "root_mean_square_difference": rms,
        "mean_signed_difference": bias,
        "relative_rms_difference_to_original_rms": relative_rms,
        "correlation": correlation,
        "area_weighted_mean_absolute_difference": area_mean_absolute,
        "area_weighted_root_mean_square_difference": area_rms,
        "area_weighted_mean_signed_difference": area_bias,
        "status": status,
        "reason": reason,
        "method": (
            "decoded isobars -> periodic bilinear interpolation to original lat/lon -> "
            "linear interpolation in log(p) to original local pressure; no extrapolation; "
            "difference = reconstructed - original"
        ),
    }


def reconstruct_grib_on_source_grid(
    paths: Sequence[Path],
    source: SourceReferenceDataset,
    *,
    technical_epoch: str,
) -> ReconstructionResult:
    """Decode GRIB and reconstruct each field on the original HDF5 grid."""
    groups = _decoded_groups(decode_grib_messages(paths))
    expected_groups = {
        (
            field_name,
            grib_valid_datetime(float(elapsed), technical_epoch).strftime(
                "%Y%m%dT%H%M"
            ),
        )
        for elapsed in source.time_seconds
        for field_name in source.fields
    }
    if set(groups) != expected_groups:
        raise ConversionError(
            "decoded GRIB reconstruction field/time groups differ from the HDF5 "
            f"reference; missing={sorted(expected_groups - set(groups))[:5]}, "
            f"unexpected={sorted(set(groups) - expected_groups)[:5]}"
        )
    rows: list[dict[str, object]] = []
    reconstructed_fields = {
        name: np.full_like(values, np.nan) for name, values in source.fields.items()
    }
    decoded_levels_by_group: dict[tuple[int, str], np.ndarray] = {}
    for time_index, elapsed in enumerate(source.time_seconds):
        stamp = grib_valid_datetime(float(elapsed), technical_epoch).strftime(
            "%Y%m%dT%H%M"
        )
        for field_name, original_field in source.fields.items():
            key = (field_name, stamp)
            if key not in groups:
                raise ConversionError(f"decoded GRIB reconstruction is missing {key}")
            messages = groups[key]
            decoded_levels = np.asarray(
                [item.pressure_level_pa for item in messages], dtype=np.float64
            )
            decoded_levels_by_group[(time_index, field_name)] = decoded_levels
            first = messages[0]
            decoded_stack = np.stack([item.values for item in messages], axis=2)
            horizontal = periodic_bilinear_interpolate(
                decoded_stack,
                first.latitude,
                first.longitude,
                source.latitude,
                source.longitude,
            )
            reconstructed = _vertical_reconstruct(
                horizontal, decoded_levels, source.pressure_pa[time_index]
            )
            reconstructed_fields[field_name][time_index] = reconstructed
            for level_index in range(source.shape[1]):
                for region_name, latitude_mask in _regions(
                    source.latitude, first.latitude
                ):
                    if not np.any(latitude_mask):
                        continue
                    rows.append(
                        _statistics_row(
                            source=source,
                            field_name=field_name,
                            time_index=time_index,
                            stamp=stamp,
                            level_index=level_index,
                            region_name=region_name,
                            latitude_mask=latitude_mask,
                            original=original_field[time_index, level_index],
                            reconstructed=reconstructed[level_index],
                            source_pressure=source.pressure_pa[
                                time_index, level_index
                            ],
                            decoded_levels=decoded_levels,
                        )
                    )
    return ReconstructionResult(rows, reconstructed_fields, decoded_levels_by_group)


def write_reconstruction_netcdf(
    path: Path,
    source: SourceReferenceDataset,
    result: ReconstructionResult,
    *,
    technical_epoch: str,
    overwrite: bool = False,
) -> Path:
    """Write original, reconstructed and signed differences on source coordinates."""
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data_vars: dict[str, object] = {
        "source_pressure": (
            ("time", "source_level", "latitude", "longitude"),
            source.pressure_pa,
            {"units": "Pa", "standard_name": "air_pressure"},
        )
    }
    for name, original in source.fields.items():
        reconstructed = result.reconstructed[name]
        attrs = {"units": source.units[name]}
        data_vars[f"{name}_original"] = (
            ("time", "source_level", "latitude", "longitude"), original, attrs
        )
        data_vars[f"{name}_reconstructed"] = (
            ("time", "source_level", "latitude", "longitude"),
            reconstructed,
            attrs,
        )
        data_vars[f"{name}_difference"] = (
            ("time", "source_level", "latitude", "longitude"),
            reconstructed - original,
            {
                **attrs,
                "long_name": "decoded GRIB1 reconstructed minus original HDF5",
            },
        )
    dataset = xr.Dataset(
        data_vars=data_vars,
        coords={
            "time": (
                "time",
                source.time_seconds,
                {"units": f"seconds since {technical_epoch}"},
            ),
            "source_level": np.arange(source.shape[1], dtype=np.int32),
            "latitude": (
                "latitude",
                source.latitude,
                {"standard_name": "latitude", "units": "degrees_north"},
            ),
            "longitude": (
                "longitude",
                source.longitude,
                {"standard_name": "longitude", "units": "degrees_east"},
            ),
        },
        attrs={
            "Conventions": "CF-1.10",
            "comparison_method": (
                "GRIB1 decoded, periodically bilinearly interpolated horizontally, "
                "then interpolated linearly in log pressure without extrapolation"
            ),
            "difference_convention": "reconstructed minus original",
            "review_status": "pending manual review by Márkó",
        },
    )
    temporary = path.with_suffix(path.suffix + ".partial")
    try:
        dataset.to_netcdf(temporary, engine="netcdf4")
        temporary.replace(path)
    finally:
        dataset.close()
        if temporary.exists():
            temporary.unlink()
    return path
