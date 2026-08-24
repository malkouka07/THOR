from datetime import datetime, timezone

import pytest

from mjolnir_fileconversions.errors import ConversionError
from mjolnir_fileconversions.processing.time import grib_valid_datetime


def test_elapsed_time_uses_technical_epoch():
    assert grib_valid_datetime(86400) == datetime(2000, 1, 2, tzinfo=timezone.utc)


def test_subminute_time_is_rejected_for_grib1():
    with pytest.raises(ConversionError, match="sub-minute"):
        grib_valid_datetime(1.0)
