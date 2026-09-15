"""Regular-grid normalization and the migrated GRIB2 horizontal remapping."""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from ..errors import ConversionError


def target_regular_grid(lat_step: float = 4.0, lon_step: float = 4.0) -> tuple[np.ndarray, np.ndarray]:
    """Create ``-90..90`` and periodic ``0..360`` coordinates without 360."""
    if lat_step <= 0 or lon_step <= 0:
        raise ConversionError("grid steps must be positive")
    nlat = round(180.0 / lat_step)
    nlon = round(360.0 / lon_step)
    if not math.isclose(nlat * lat_step, 180.0, abs_tol=1e-10):
        raise ConversionError("latitude step must divide 180 exactly")
    if not math.isclose(nlon * lon_step, 360.0, abs_tol=1e-10):
        raise ConversionError("longitude step must divide 360 exactly")
    latitude = np.linspace(-90.0, 90.0, nlat + 1, dtype=np.float64)
    longitude = np.arange(nlon, dtype=np.float64) * (360.0 / nlon)
    latitude[[0, -1]] = (-90.0, 90.0)
    longitude[0] = 0.0
    return latitude, longitude


def normalize_source_grid(
    latitude: np.ndarray,
    longitude: np.ndarray,
    arrays: Sequence[np.ndarray],
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    """Sort coordinates and matching arrays, normalizing longitude only once."""
    latitude = np.asarray(latitude, dtype=np.float64)
    longitude = np.mod(np.asarray(longitude, dtype=np.float64), 360.0)
    if latitude.ndim != 1 or longitude.ndim != 1:
        raise ConversionError("only independent 1-D regular coordinates are supported")
    lat_order = np.argsort(latitude)
    lon_order = np.argsort(longitude)
    latitude = latitude[lat_order]
    longitude = longitude[lon_order]
    if len(np.unique(latitude)) != len(latitude):
        raise ConversionError("duplicate latitude values")
    if len(np.unique(longitude)) != len(longitude):
        raise ConversionError("duplicate longitude values after [0,360) normalization")
    if np.any(np.diff(latitude) <= 0) or np.any(np.diff(longitude) <= 0):
        raise ConversionError("coordinates must be strictly increasing")
    result: list[np.ndarray] = []
    for array in arrays:
        values = np.asarray(array, dtype=np.float64)
        if values.shape[:2] != (latitude.size, longitude.size):
            raise ConversionError(
                f"field shape {values.shape} does not start with latitude/longitude "
                f"{(latitude.size, longitude.size)}"
            )
        result.append(values[lat_order][:, lon_order, ...])
    return latitude, longitude, result


def is_regular_periodic(latitude: np.ndarray, longitude: np.ndarray) -> bool:
    if latitude.size < 2 or longitude.size < 2:
        return False
    lat_d = np.diff(latitude)
    lon_d = np.diff(longitude)
    return bool(
        np.allclose(lat_d, lat_d[0], atol=1e-9, rtol=0)
        and np.allclose(lon_d, lon_d[0], atol=1e-9, rtol=0)
        and math.isclose(longitude[-1] + lon_d[0] - longitude[0], 360.0, abs_tol=1e-9)
    )


def grids_equal(
    source_lat: np.ndarray,
    source_lon: np.ndarray,
    target_lat: np.ndarray,
    target_lon: np.ndarray,
) -> bool:
    return bool(
        source_lat.shape == target_lat.shape
        and source_lon.shape == target_lon.shape
        and np.allclose(source_lat, target_lat, atol=1e-9, rtol=0)
        and np.allclose(source_lon, target_lon, atol=1e-9, rtol=0)
    )


def periodic_bilinear_interpolate(
    field: np.ndarray,
    source_latitude: np.ndarray,
    source_longitude: np.ndarray,
    target_latitude: np.ndarray,
    target_longitude: np.ndarray,
) -> np.ndarray:
    """Bilinearly interpolate a regular field with periodic longitude.

    Unlike :func:`horizontal_remap`, this primitive does not invent values at
    poles.  Every target latitude must lie inside the source latitude range.
    Trailing field dimensions are retained.
    """
    values = np.asarray(field, dtype=np.float64)
    source_latitude = np.asarray(source_latitude, dtype=np.float64)
    source_longitude = np.asarray(source_longitude, dtype=np.float64)
    target_latitude = np.asarray(target_latitude, dtype=np.float64)
    target_longitude = np.mod(np.asarray(target_longitude, dtype=np.float64), 360.0)
    if values.shape[:2] != (source_latitude.size, source_longitude.size):
        raise ConversionError(
            "periodic interpolation field does not match source coordinates"
        )
    for name, coordinate in (
        ("source latitude", source_latitude),
        ("source longitude", source_longitude),
        ("target latitude", target_latitude),
        ("target longitude", target_longitude),
    ):
        if coordinate.ndim != 1 or coordinate.size == 0 or np.any(~np.isfinite(coordinate)):
            raise ConversionError(f"{name} must be a non-empty finite 1-D coordinate")
    if np.any(np.diff(source_latitude) <= 0) or np.any(np.diff(source_longitude) <= 0):
        raise ConversionError("source coordinates must be strictly increasing")
    if (
        target_latitude.min() < source_latitude[0] - 1e-10
        or target_latitude.max() > source_latitude[-1] + 1e-10
    ):
        raise ConversionError("target latitude would require extrapolation")
    lon_ext = np.concatenate(
        (
            [source_longitude[-1] - 360.0],
            source_longitude,
            [source_longitude[0] + 360.0],
        )
    )
    field_ext = np.concatenate(
        (values[:, -1:, ...], values, values[:, :1, ...]), axis=1
    )
    interpolator = RegularGridInterpolator(
        (source_latitude, lon_ext), field_ext, method="linear", bounds_error=True
    )
    lat_mesh, lon_mesh = np.meshgrid(
        target_latitude, target_longitude, indexing="ij"
    )
    points = np.column_stack((lat_mesh.ravel(), lon_mesh.ravel()))
    return interpolator(points).reshape(
        target_latitude.size, target_longitude.size, *values.shape[2:]
    )


def horizontal_remap(
    field: np.ndarray,
    source_latitude: np.ndarray,
    source_longitude: np.ndarray,
    target_latitude: np.ndarray,
    target_longitude: np.ndarray,
    *,
    pole_kind: str,
) -> np.ndarray:
    """Periodic bilinear interpolation with explicit, non-extrapolated poles.

    This is the numerical procedure migrated from the existing GRIB2 work.
    Scalar poles use the zonal mean of the nearest source ring. Geographic
    horizontal components use zero at the exact pole, where the east/north
    basis is singular; both GRIB editions receive this same result.
    """
    field = np.asarray(field, dtype=np.float64)
    if grids_equal(source_latitude, source_longitude, target_latitude, target_longitude):
        return field.copy()
    if pole_kind not in {"scalar", "horizontal_vector"}:
        raise ConversionError(f"unknown pole kind: {pole_kind}")
    if target_latitude[0] != -90.0 or target_latitude[-1] != 90.0:
        raise ConversionError("target latitude must contain the exact poles")
    interior = target_latitude[1:-1]
    mapped = periodic_bilinear_interpolate(
        field,
        source_latitude,
        source_longitude,
        interior,
        target_longitude,
    )
    tail = field.shape[2:]
    output = np.empty((target_latitude.size, target_longitude.size, *tail), dtype=np.float64)
    output[1:-1] = mapped
    if pole_kind == "horizontal_vector":
        output[0] = 0.0
        output[-1] = 0.0
    else:
        output[0] = np.mean(field[0], axis=0)[None, ...]
        output[-1] = np.mean(field[-1], axis=0)[None, ...]
    return output
