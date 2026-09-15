"""Input adapters for supported post-processed formats."""

from .hdf5_reader import read_processed_hdf5, read_processed_hdf5_collection
from .netcdf_reader import read_netcdf, read_netcdf_collection

__all__ = [
    "read_processed_hdf5",
    "read_processed_hdf5_collection",
    "read_netcdf",
    "read_netcdf_collection",
]
