"""Numerical GRIB1/GRIB2 parity after format-specific packing."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np

from ..errors import ConversionError
from .grib_validation import DecodedGribMessage, decode_grib_messages


def _group(messages: Sequence[DecodedGribMessage]) -> dict[tuple[str, str, int], DecodedGribMessage]:
    result: dict[tuple[str, str, int], DecodedGribMessage] = {}
    for item in messages:
        key = (item.field_name, item.valid_time, item.pressure_level_pa)
        if key in result:
            raise ConversionError(f"duplicate GRIB parity key: {key}")
        result[key] = item
    return result


def compare_grib_collections(
    grib1_paths: Sequence[Path],
    grib2_paths: Sequence[Path],
    *,
    packing_tolerance: float = 1e-4,
) -> list[dict[str, object]]:
    grib1 = _group(decode_grib_messages(grib1_paths))
    grib2 = _group(decode_grib_messages(grib2_paths))
    common = sorted(set(grib1).intersection(grib2))
    if not common:
        # hPa-rounded GRIB1 changes the decoded level. Pair by stable field/time/order.
        left = sorted(grib1.values(), key=lambda item: (item.field_name, item.valid_time, item.message_index))
        right = sorted(grib2.values(), key=lambda item: (item.field_name, item.valid_time, item.message_index))
        if len(left) != len(right):
            raise ConversionError("GRIB collections have no common keys and different message counts")
        pairs = list(zip(left, right))
    else:
        pairs = [(grib1[key], grib2[key]) for key in common]
    rows: list[dict[str, object]] = []
    for left, right in pairs:
        if left.field_name != right.field_name or left.valid_time != right.valid_time:
            raise ConversionError("GRIB parity message ordering differs")
        if left.values.shape != right.values.shape:
            raise ConversionError(f"GRIB parity grid mismatch: {left.values.shape} vs {right.values.shape}")
        difference = left.values - right.values
        finite = np.isfinite(difference)
        diff = difference[finite]
        scale = np.sqrt(np.mean(np.square(right.values[np.isfinite(right.values)])))
        rms = float(np.sqrt(np.mean(np.square(diff)))) if diff.size else float("nan")
        max_abs = float(np.max(np.abs(diff))) if diff.size else float("nan")
        rows.append(
            {
                "input_file": f"{left.path};{right.path}",
                "variable": left.field_name,
                "time": left.valid_time,
                "pressure_level_pa": right.pressure_level_pa,
                "grid_shape": "x".join(map(str, left.values.shape)),
                "grib1_min": float(np.nanmin(left.values)),
                "grib2_min": float(np.nanmin(right.values)),
                "grib1_max": float(np.nanmax(left.values)),
                "grib2_max": float(np.nanmax(right.values)),
                "max_absolute_difference": max_abs,
                "mean_absolute_difference": float(np.mean(np.abs(diff))),
                "rms_difference": rms,
                "relative_rms_difference": rms / max(scale, 1e-30),
                "packing_tolerance": packing_tolerance,
                "parity_status": "passed" if max_abs <= packing_tolerance else "failed",
                "notes": f"decoded GRIB1 level={left.pressure_level_pa} Pa",
            }
        )
    return rows
