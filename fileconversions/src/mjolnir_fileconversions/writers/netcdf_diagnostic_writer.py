"""Optional standard NetCDF diagnostic output of canonical writer input."""

from __future__ import annotations

from pathlib import Path

import xarray as xr

from ..models import CanonicalDataset


def write_netcdf_diagnostic(dataset: CanonicalDataset, path: Path, *, overwrite: bool = False) -> Path:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = xr.Dataset(
        data_vars={
            name: (("time", "level", "latitude", "longitude"), values, {"units": dataset.units[name]})
            for name, values in dataset.fields.items()
        },
        coords={
            "time": ("time", dataset.time_seconds, {"units": "seconds since 2000-01-01 00:00:00", "calendar": "proleptic_gregorian"}),
            "level": ("level", dataset.level_pa.astype("int32"), {"standard_name": "air_pressure", "units": "Pa", "positive": "down"}),
            "latitude": ("latitude", dataset.latitude, {"standard_name": "latitude", "units": "degrees_north"}),
            "longitude": ("longitude", dataset.longitude, {"standard_name": "longitude", "units": "degrees_east"}),
        },
        attrs={"Conventions": "CF-1.10", "review_status": "pending manual review by Márkó"},
    )
    temporary = path.with_suffix(path.suffix + ".partial")
    try:
        data.to_netcdf(temporary, engine="netcdf4")
        temporary.replace(path)
    finally:
        data.close()
        if temporary.exists():
            temporary.unlink()
    return path
