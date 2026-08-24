"""Numerical summary helpers used by conversion and validation reports."""

from __future__ import annotations

import numpy as np


def finite_statistics(values: np.ndarray) -> dict[str, float | int]:
    data = np.asarray(values, dtype=np.float64)
    finite = np.isfinite(data)
    selected = data[finite]
    if selected.size == 0:
        return {
            "minimum": float("nan"),
            "maximum": float("nan"),
            "mean": float("nan"),
            "standard_deviation": float("nan"),
            "missing_count": int(data.size),
        }
    return {
        "minimum": float(selected.min()),
        "maximum": float(selected.max()),
        "mean": float(selected.mean()),
        "standard_deviation": float(selected.std()),
        "missing_count": int(data.size - selected.size),
    }


def area_weighted_mean(values: np.ndarray, latitude: np.ndarray) -> float:
    data = np.asarray(values, dtype=np.float64)
    weights = np.cos(np.deg2rad(latitude))
    shape = [1] * data.ndim
    shape[-2] = latitude.size
    weights = np.broadcast_to(weights.reshape(shape), data.shape)
    finite = np.isfinite(data)
    return float(np.sum(np.where(finite, data * weights, 0.0)) / np.sum(np.where(finite, weights, 0.0)))
