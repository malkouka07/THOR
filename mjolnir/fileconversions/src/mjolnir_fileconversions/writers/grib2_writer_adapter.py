"""GRIB2 writer adapter fed by the same canonical arrays as GRIB1."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

import numpy as np

from ..errors import ConversionError
from ..models import CanonicalDataset
from .grib_common import (
    GRIB2_PARAMETERS,
    eccodes_module,
    layout_paths,
    refuse_existing,
    set_regular_grid,
    set_valid_time,
    set_values,
    valid_datetime,
    write_sidecar,
)


def write_grib2_message(
    stream: BinaryIO,
    *,
    field_name: str,
    values: np.ndarray,
    latitude: np.ndarray,
    longitude: np.ndarray,
    pressure_level_pa: int,
    valid: datetime,
    bits_per_value: int = 24,
) -> None:
    if field_name not in GRIB2_PARAMETERS:
        raise ConversionError(f"No GRIB2 parameter mapping for {field_name}")
    codes = eccodes_module()
    handle = codes.codes_grib_new_from_samples("regular_ll_pl_grib2")
    try:
        discipline, category, number, _ = GRIB2_PARAMETERS[field_name]
        codes.codes_set(handle, "discipline", discipline)
        codes.codes_set(handle, "parameterCategory", category)
        codes.codes_set(handle, "parameterNumber", number)
        codes.codes_set(handle, "typeOfLevel", "isobaricInPa")
        codes.codes_set(handle, "level", int(round(pressure_level_pa)))
        set_regular_grid(codes, handle, latitude, longitude)
        set_valid_time(codes, handle, valid)
        set_values(codes, handle, values, bits_per_value)
        codes.codes_write(handle, stream)
    finally:
        codes.codes_release(handle)


def write_grib2_dataset(
    dataset: CanonicalDataset,
    output_dir: Path,
    *,
    file_layout: str = "per-variable",
    overwrite: bool = False,
    bits_per_value: int = 24,
    technical_epoch: str = "2000-01-01T00:00:00Z",
) -> list[Path]:
    dataset.validate()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = layout_paths(dataset, output_dir, "grib2", file_layout)
    unique = sorted(set(paths.values()))
    refuse_existing(unique, overwrite)
    temporary = {path: path.with_suffix(path.suffix + ".partial") for path in unique}
    for path in temporary.values():
        if path.exists():
            path.unlink()
    try:
        with ExitStack() as stack:
            streams = {path: stack.enter_context(temporary[path].open("wb")) for path in unique}
            for time_index in range(dataset.time_seconds.size):
                valid = valid_datetime(dataset, time_index, technical_epoch)
                for field_name, field in dataset.fields.items():
                    for level_index, level in enumerate(dataset.level_pa):
                        write_grib2_message(
                            streams[paths[(time_index, field_name)]],
                            field_name=field_name,
                            values=field[time_index, level_index],
                            latitude=dataset.latitude,
                            longitude=dataset.longitude,
                            pressure_level_pa=int(round(level)),
                            valid=valid,
                            bits_per_value=bits_per_value,
                        )
        for path in unique:
            temporary[path].replace(path)
            write_sidecar(
                path,
                dataset,
                edition=2,
                level_encoding="not applicable",
                technical_epoch=technical_epoch,
            )
    except Exception:
        for path in temporary.values():
            if path.exists():
                path.unlink()
        raise
    return unique
