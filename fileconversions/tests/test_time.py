from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from mjolnir_fileconversions.errors import ConversionError
from mjolnir_fileconversions.processing.time import grib_valid_datetime
from mjolnir_fileconversions.writers.grib_common import valid_datetime


def test_elapsed_time_uses_technical_epoch():
    assert grib_valid_datetime(86400) == datetime(2000, 1, 2, tzinfo=timezone.utc)


def test_subminute_time_is_rejected_for_grib1():
    with pytest.raises(ConversionError, match="sub-minute"):
        grib_valid_datetime(1.0)


def test_absolute_valid_time_with_seconds_is_rejected():
    dataset = SimpleNamespace(
        metadata={"absolute_valid_times_utc": ["2000-01-01T00:00:01Z"]},
        time_seconds=np.array([0.0]),
    )
    with pytest.raises(ConversionError, match="sub-minute"):
        valid_datetime(dataset, 0)
