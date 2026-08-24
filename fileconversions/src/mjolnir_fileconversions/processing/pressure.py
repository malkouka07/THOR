"""Pressure normalization, target selection and column interpolation."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..errors import ConversionError


@dataclass(frozen=True)
class PressureMapping:
    source_level: str
    source_units: str
    source_level_pa: float
    target_level_pa: int
    absolute_error_pa: float
    relative_error: float
    interpolation_performed: bool
    interpolation_method: str
    grib2_level_encoding: str = "isobaricInPa"
    grib1_level_encoding: str = "pending writer policy"
    grib1_exactly_representable: bool = False
    compatibility_mode: str = "pending"
    notes: str = ""

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def pressure_factor(units: str) -> float:
    normalized = units.strip().lower().replace(" ", "")
    if normalized in {"pa", "pascal", "pascals"}:
        return 1.0
    if normalized in {"hpa", "mbar", "millibar", "millibars"}:
        return 100.0
    if normalized in {"kpa"}:
        return 1000.0
    if normalized in {"bar", "bars"}:
        return 100000.0
    raise ConversionError(f"unsupported or missing pressure units: {units!r}")


def to_pa(values: np.ndarray, units: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64) * pressure_factor(units)
    if np.any(~np.isfinite(result)) or np.any(result <= 0):
        raise ConversionError("pressure contains non-positive or non-finite values")
    return result


def area_weighted_reference(pressure: np.ndarray, latitude: np.ndarray) -> np.ndarray:
    pressure = np.asarray(pressure, dtype=np.float64)
    weights = np.cos(np.deg2rad(latitude))[:, None, None]
    weights = np.broadcast_to(weights, pressure.shape)
    finite = np.isfinite(pressure)
    denominator = np.sum(np.where(finite, weights, 0.0), axis=(0, 1))
    if np.any(denominator == 0):
        raise ConversionError("a pressure layer has no finite columns")
    return np.sum(np.where(finite, pressure * weights, 0.0), axis=(0, 1)) / denominator


def derive_integer_levels(
    reference_pa: np.ndarray,
    column_pressure_pa: np.ndarray | None = None,
    boundary_margin_pa: float = 1.0,
) -> tuple[np.ndarray, list[PressureMapping]]:
    reference = np.asarray(reference_pa, dtype=np.float64)
    direction = np.sign(np.diff(reference))
    if direction.size and not (np.all(direction > 0) or np.all(direction < 0)):
        raise ConversionError("reference pressure is not monotonic")
    target = np.rint(reference).astype(np.int64)
    if len(np.unique(target)) != len(target):
        raise ConversionError("integer-Pa rounding collapses pressure levels")
    if column_pressure_pa is not None:
        columns = np.asarray(column_pressure_pa, dtype=np.float64)
        if columns.shape[-1] != reference.size:
            raise ConversionError("column pressure level dimension mismatch")
        decreasing = reference[0] > reference[-1]
        lower = columns[..., 0] if decreasing else columns[..., -1]
        upper = columns[..., -1] if decreasing else columns[..., 0]
        safe_bottom = int(math.floor(float(np.nanmin(lower)) - boundary_margin_pa))
        safe_top = int(math.ceil(float(np.nanmax(upper)) + boundary_margin_pa))
        if decreasing:
            target[0] = min(target[0], safe_bottom)
            target[-1] = max(target[-1], safe_top)
        else:
            target[-1] = min(target[-1], safe_bottom)
            target[0] = max(target[0], safe_top)
    if target.size > 1 and not (
        np.all(np.diff(target) > 0) or np.all(np.diff(target) < 0)
    ):
        raise ConversionError("derived integer-Pa pressure is not monotonic")
    rows = [
        PressureMapping(
            source_level=str(index),
            source_units="Pa",
            source_level_pa=float(source),
            target_level_pa=int(destination),
            absolute_error_pa=abs(float(destination) - float(source)),
            relative_error=abs(float(destination) - float(source)) / float(source),
            interpolation_performed=not math.isclose(source, destination, abs_tol=1e-12),
            interpolation_method="linear in log(p)" if not math.isclose(source, destination, abs_tol=1e-12) else "none",
        )
        for index, (source, destination) in enumerate(zip(reference, target))
    ]
    return target, rows


def interpolate_log_pressure(
    field: np.ndarray,
    source_pressure_pa: np.ndarray,
    target_pressure_pa: np.ndarray,
) -> np.ndarray:
    """Interpolate the last dimension per column without extrapolation."""
    values = np.asarray(field, dtype=np.float64)
    pressure = np.asarray(source_pressure_pa, dtype=np.float64)
    target = np.asarray(target_pressure_pa, dtype=np.float64)
    if pressure.ndim == 1:
        pressure = np.broadcast_to(pressure, values.shape)
    if values.shape != pressure.shape:
        raise ConversionError(f"field/pressure shape mismatch: {values.shape} vs {pressure.shape}")
    if np.any(~np.isfinite(values)) or np.any(~np.isfinite(pressure)):
        raise ConversionError("field or pressure contains NaN/Inf before interpolation")
    output = np.empty(values.shape[:-1] + (target.size,), dtype=np.float64)
    for index in np.ndindex(values.shape[:-1]):
        pcol = pressure[index]
        fcol = values[index]
        if pcol[0] > pcol[-1]:
            pwork, fwork = pcol[::-1], fcol[::-1]
        else:
            pwork, fwork = pcol, fcol
        if np.any(np.diff(pwork) <= 0):
            raise ConversionError(f"pressure is not strictly monotonic in column {index}")
        if target.min() < pwork[0] - 1e-8 or target.max() > pwork[-1] + 1e-8:
            raise ConversionError(f"target pressure would extrapolate in column {index}")
        output[index] = np.interp(np.log(target), np.log(pwork), fwork)
    return output
