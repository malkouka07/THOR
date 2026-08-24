"""Physically explicit geometric-W to pressure-omega handling."""

from __future__ import annotations

import numpy as np

from ..errors import ScientificMappingError


OMEGA_UNITS = {"pa/s", "pas-1", "pas^-1", "pas**-1"}
GEOMETRIC_UNITS = {"m/s", "ms-1", "ms^-1", "ms**-1"}


def normalize_units(units: str | None) -> str:
    return (units or "").strip().lower().replace(" ", "")


def is_omega_units(units: str | None) -> bool:
    return normalize_units(units) in OMEGA_UNITS


def is_geometric_units(units: str | None) -> bool:
    return normalize_units(units) in GEOMETRIC_UNITS


def resolve_omega(
    *,
    mode: str,
    native_omega: np.ndarray | None = None,
    native_units: str | None = None,
    geometric_w: np.ndarray | None = None,
    density: np.ndarray | None = None,
    gravity_m_s2: float | None = None,
) -> tuple[np.ndarray | None, str]:
    """Return omega in Pa/s or fail rather than relabeling geometric W."""
    if mode == "omit":
        return None, "omitted by explicit request"
    if native_omega is not None and is_omega_units(native_units):
        return np.asarray(native_omega, dtype=np.float64), "native pressure omega"
    if mode in {"strict", "native-omega"}:
        raise ScientificMappingError(
            "No verified native pressure vertical velocity in Pa s-1 is available. "
            "The Mjolnir W field is geometric m s-1; use --vertical-velocity-mode "
            "hydrostatic with verified density/gravity, or omit omega."
        )
    if mode == "model-defined":
        raise ScientificMappingError(
            "No model-defined exact Dp/Dt formula was identified in this input"
        )
    if mode != "hydrostatic":
        raise ScientificMappingError(f"unsupported vertical velocity mode: {mode}")
    if geometric_w is None or density is None:
        raise ScientificMappingError("hydrostatic omega requires collocated W and density")
    if gravity_m_s2 is None or not np.isfinite(gravity_m_s2) or gravity_m_s2 <= 0:
        raise ScientificMappingError("hydrostatic omega requires verified positive planet gravity")
    w = np.asarray(geometric_w, dtype=np.float64)
    rho = np.asarray(density, dtype=np.float64)
    if w.shape != rho.shape:
        raise ScientificMappingError(f"W/density shape mismatch: {w.shape} vs {rho.shape}")
    if np.any(~np.isfinite(w)) or np.any(~np.isfinite(rho)) or np.any(rho <= 0):
        raise ScientificMappingError("W/density is non-finite or density is non-positive")
    return -rho * float(gravity_m_s2) * w, "hydrostatic approximation omega=-rho*g*w; W positive upward"
