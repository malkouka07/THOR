"""Canonical in-memory data model shared by every writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .errors import ConversionError


@dataclass(frozen=True)
class PlanetParameters:
    """Planet parameters required by downstream physical transformations."""

    name: str = "unknown"
    radius_m: float | None = None
    gravity_m_s2: float | None = None
    rotation_rate_s1: float | None = None
    gas_constant_j_kg_k: float | None = None
    heat_capacity_j_kg_k: float | None = None
    reference_pressure_pa: float | None = None
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "planet": self.name,
            "radius_m": self.radius_m,
            "gravity_m_s2": self.gravity_m_s2,
            "rotation_rate_s1": self.rotation_rate_s1,
            "gas_constant_j_kg_k": self.gas_constant_j_kg_k,
            "heat_capacity_j_kg_k": self.heat_capacity_j_kg_k,
            "reference_pressure_pa": self.reference_pressure_pa,
            "source": self.source,
        }


@dataclass(frozen=True)
class ProcessingStage:
    """Evidence for a transformation that happened upstream or downstream."""

    input_file: str
    field: str
    detected_grid_stage: str
    detected_vector_stage: str
    detected_vertical_stage: str
    detected_units: str
    required_next_step: str
    skipped_as_already_completed: str
    evidence: str

    def as_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


@dataclass
class SourceReferenceDataset:
    """Original regular-grid HDF5 fields retained for reconstruction checks.

    Fields and pressure use ``(time, source_level, latitude, longitude)``.  A
    four-dimensional pressure array also represents height-grid products whose
    pressure varies from column to column.
    """

    time_seconds: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    pressure_pa: np.ndarray
    fields: dict[str, np.ndarray]
    units: dict[str, str]
    source_files: list[Path] = field(default_factory=list)
    source_dataset_names: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.time_seconds = np.asarray(self.time_seconds, dtype=np.float64)
        self.latitude = np.asarray(self.latitude, dtype=np.float64)
        self.longitude = np.asarray(self.longitude, dtype=np.float64)
        self.pressure_pa = np.asarray(self.pressure_pa, dtype=np.float64)
        self.fields = {
            name: np.asarray(values, dtype=np.float64)
            for name, values in self.fields.items()
        }
        self.validate()

    @property
    def shape(self) -> tuple[int, int, int, int]:
        return self.pressure_pa.shape

    def validate(self) -> None:
        if self.time_seconds.ndim != 1 or self.time_seconds.size == 0:
            raise ConversionError("source-reference time must be non-empty and 1-D")
        if self.time_seconds.size > 1 and np.any(np.diff(self.time_seconds) <= 0):
            raise ConversionError("source-reference time must be strictly increasing")
        for name, coordinate in (
            ("latitude", self.latitude),
            ("longitude", self.longitude),
        ):
            if coordinate.ndim != 1 or coordinate.size == 0:
                raise ConversionError(
                    f"source-reference {name} must be non-empty and 1-D"
                )
            if np.any(~np.isfinite(coordinate)) or (
                coordinate.size > 1 and np.any(np.diff(coordinate) <= 0)
            ):
                raise ConversionError(
                    f"source-reference {name} must be finite and strictly increasing"
                )
        if self.pressure_pa.ndim != 4:
            raise ConversionError(
                "source-reference pressure must use time, level, latitude, longitude"
            )
        expected = (
            self.time_seconds.size,
            self.pressure_pa.shape[1],
            self.latitude.size,
            self.longitude.size,
        )
        if self.pressure_pa.shape != expected:
            raise ConversionError(
                f"source-reference pressure shape {self.pressure_pa.shape} != {expected}"
            )
        if np.any(~np.isfinite(self.pressure_pa)) or np.any(self.pressure_pa <= 0):
            raise ConversionError(
                "source-reference pressure contains non-positive or non-finite values"
            )
        pressure_steps = np.diff(self.pressure_pa, axis=1)
        if pressure_steps.size:
            descending = np.all(pressure_steps < 0, axis=1)
            ascending = np.all(pressure_steps > 0, axis=1)
            if not np.all(descending | ascending):
                raise ConversionError(
                    "source-reference pressure is not strictly monotonic in every column"
                )
        for name, values in self.fields.items():
            if values.shape != expected:
                raise ConversionError(
                    f"source-reference {name} shape {values.shape} != {expected}"
                )
            if name not in self.units:
                raise ConversionError(f"missing source-reference unit for {name}")
            if np.any(np.isinf(values)):
                raise ConversionError(f"source-reference {name} contains Inf")
            if name == "air_temperature":
                finite = values[np.isfinite(values)]
                if np.any(finite <= 0):
                    raise ConversionError(
                        "source-reference absolute air_temperature must be positive Kelvin"
                    )


@dataclass
class CanonicalDataset:
    """Fields on ``(time, level, latitude, longitude)`` pressure coordinates."""

    time_seconds: np.ndarray
    level_pa: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    fields: dict[str, np.ndarray]
    units: dict[str, str]
    source_files: list[Path] = field(default_factory=list)
    planet: PlanetParameters = field(default_factory=PlanetParameters)
    metadata: dict[str, Any] = field(default_factory=dict)
    stages: list[ProcessingStage] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.time_seconds = np.asarray(self.time_seconds, dtype=np.float64)
        self.level_pa = np.asarray(self.level_pa, dtype=np.float64)
        self.latitude = np.asarray(self.latitude, dtype=np.float64)
        self.longitude = np.asarray(self.longitude, dtype=np.float64)
        self.fields = {
            name: np.asarray(values, dtype=np.float64)
            for name, values in self.fields.items()
        }
        self.validate()

    @property
    def shape(self) -> tuple[int, int, int, int]:
        return (
            self.time_seconds.size,
            self.level_pa.size,
            self.latitude.size,
            self.longitude.size,
        )

    def validate(self) -> None:
        """Reject ambiguous orientation, coordinates and invalid physical values."""
        for name, coordinate in (
            ("time", self.time_seconds),
            ("level", self.level_pa),
            ("latitude", self.latitude),
            ("longitude", self.longitude),
        ):
            if coordinate.ndim != 1 or coordinate.size == 0:
                raise ConversionError(f"{name} must be a non-empty 1-D coordinate")
            if not np.all(np.isfinite(coordinate)):
                raise ConversionError(f"{name} contains NaN/Inf")
        if self.time_seconds.size > 1 and np.any(np.diff(self.time_seconds) <= 0):
            raise ConversionError("time must be strictly increasing")
        if np.any(self.level_pa <= 0):
            raise ConversionError("pressure levels must be positive Pa values")
        level_diff = np.diff(self.level_pa)
        if level_diff.size and not (np.all(level_diff > 0) or np.all(level_diff < 0)):
            raise ConversionError("pressure levels must be strictly monotonic")
        if self.latitude.size > 1 and np.any(np.diff(self.latitude) <= 0):
            raise ConversionError("latitude must be strictly increasing south-to-north")
        if self.longitude.size > 1 and np.any(np.diff(self.longitude) <= 0):
            raise ConversionError("longitude must be strictly increasing")
        if np.any(self.longitude < 0) or np.any(self.longitude >= 360):
            raise ConversionError("longitude must use the [0, 360) convention")
        expected = self.shape
        for name, values in self.fields.items():
            if values.shape != expected:
                raise ConversionError(
                    f"{name} shape {values.shape} is not canonical {expected}"
                )
            if name not in self.units:
                raise ConversionError(f"missing unit metadata for {name}")
            if np.any(np.isinf(values)):
                raise ConversionError(f"{name} contains Inf")
        if "omega" in self.fields and self.units.get("omega") != "Pa s-1":
            raise ConversionError("canonical omega must use units 'Pa s-1'")
        if (
            "air_temperature" in self.fields
            and self.units.get("air_temperature") != "K"
        ):
            raise ConversionError("canonical air_temperature must use units 'K'")
        if "air_temperature" in self.fields:
            finite_temperature = self.fields["air_temperature"][
                np.isfinite(self.fields["air_temperature"])
            ]
            if np.any(finite_temperature <= 0):
                raise ConversionError(
                    "canonical absolute air_temperature must be positive Kelvin"
                )

    def subset_fields(self, names: list[str]) -> "CanonicalDataset":
        missing = set(names) - set(self.fields)
        if missing:
            raise ConversionError(f"requested canonical fields are absent: {sorted(missing)}")
        return CanonicalDataset(
            self.time_seconds,
            self.level_pa,
            self.latitude,
            self.longitude,
            {name: self.fields[name] for name in names},
            {name: self.units[name] for name in names},
            self.source_files,
            self.planet,
            self.metadata.copy(),
            list(self.stages),
        )
