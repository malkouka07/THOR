"""Format-specific writers consuming the same canonical fields."""

from .grib1_writer import write_grib1_dataset
from .grib2_writer_adapter import write_grib2_dataset

__all__ = ["write_grib1_dataset", "write_grib2_dataset"]
