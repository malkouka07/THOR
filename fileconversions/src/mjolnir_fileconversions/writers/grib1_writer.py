"""Controlled GRIB Edition 1 encoder using WMO table-2 parameters."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

import numpy as np

from ..errors import ConversionError
from ..models import CanonicalDataset
from .grib_common import (
    GRIB1_PARAMETERS,
    EncodedLevel,
    eccodes_module,
    encode_grib1_level,
    layout_paths,
    refuse_existing,
    set_regular_grid,
    set_valid_time,
    set_values,
    valid_datetime,
    write_sidecar,
)


def write_grib1_message(
    stream: BinaryIO,
    *,
    field_name: str,
    values: np.ndarray,
    latitude: np.ndarray,
    longitude: np.ndarray,
    pressure_level_pa: float,
    valid: datetime,
    level_encoding: str,
    max_absolute_error_pa: float = 50.0,
    max_relative_error: float = 0.001,
    bits_per_value: int = 24,
) -> EncodedLevel:
    if field_name not in GRIB1_PARAMETERS:
        raise ConversionError(f"No GRIB1 parameter mapping for {field_name}")
    codes = eccodes_module()
    encoded = encode_grib1_level(
        pressure_level_pa,
        level_encoding,
        max_absolute_error_pa=max_absolute_error_pa,
        max_relative_error=max_relative_error,
    )
    handle = codes.codes_grib_new_from_samples("regular_ll_pl_grib1")
    try:
        parameter, _ = GRIB1_PARAMETERS[field_name]
        codes.codes_set(handle, "edition", 1)
        codes.codes_set(handle, "centre", 98)
        codes.codes_set(handle, "subCentre", 0)
        codes.codes_set(handle, "table2Version", 2)
        codes.codes_set(handle, "indicatorOfParameter", parameter)
        codes.codes_set(handle, "typeOfLevel", encoded.type_of_level)
        codes.codes_set(handle, "level", encoded.encoded_level)
        set_regular_grid(codes, handle, latitude, longitude)
        set_valid_time(codes, handle, valid)
        set_values(codes, handle, values, bits_per_value)
        codes.codes_write(handle, stream)
    finally:
        codes.codes_release(handle)
    return encoded


def write_grib1_dataset(
    dataset: CanonicalDataset,
    output_dir: Path,
    *,
    file_layout: str = "per-variable",
    level_encoding: str = "strict",
    overwrite: bool = False,
    max_absolute_error_pa: float = 50.0,
    max_relative_error: float = 0.001,
    bits_per_value: int = 24,
    technical_epoch: str = "2000-01-01T00:00:00Z",
) -> tuple[list[Path], list[EncodedLevel]]:
    dataset.validate()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = layout_paths(dataset, output_dir, "grib1", file_layout)
    unique = sorted(set(paths.values()))
    refuse_existing(unique, overwrite)
    temporary = {path: path.with_suffix(path.suffix + ".partial") for path in unique}
    for path in temporary.values():
        if path.exists():
            path.unlink()
    encoded_rows: list[EncodedLevel] = []
    try:
        with ExitStack() as stack:
            streams = {path: stack.enter_context(temporary[path].open("wb")) for path in unique}
            for time_index in range(dataset.time_seconds.size):
                valid = valid_datetime(dataset, time_index, technical_epoch)
                for field_name, field in dataset.fields.items():
                    for level_index, level in enumerate(dataset.level_pa):
                        encoded_rows.append(
                            write_grib1_message(
                                streams[paths[(time_index, field_name)]],
                                field_name=field_name,
                                values=field[time_index, level_index],
                                latitude=dataset.latitude,
                                longitude=dataset.longitude,
                                pressure_level_pa=level,
                                valid=valid,
                                level_encoding=level_encoding,
                                max_absolute_error_pa=max_absolute_error_pa,
                                max_relative_error=max_relative_error,
                                bits_per_value=bits_per_value,
                            )
                        )
        for path in unique:
            temporary[path].replace(path)
            write_sidecar(
                path,
                dataset,
                edition=1,
                level_encoding=level_encoding,
                technical_epoch=technical_epoch,
            )
    except Exception:
        for path in temporary.values():
            if path.exists():
                path.unlink()
        raise
    return unique, encoded_rows
