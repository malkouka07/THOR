"""Model-elapsed-time handling for GRIB technical reference dates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from ..errors import ConversionError


DEFAULT_EPOCH = "2000-01-01T00:00:00Z"


def parse_epoch(value: str = DEFAULT_EPOCH) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConversionError(f"invalid technical reference epoch: {value}") from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def grib_valid_datetime(elapsed_seconds: float, epoch: str = DEFAULT_EPOCH) -> datetime:
    if not np.isfinite(elapsed_seconds) or elapsed_seconds < 0:
        raise ConversionError("model elapsed time must be finite and non-negative")
    rounded_minutes = round(elapsed_seconds / 60.0)
    if not np.isclose(elapsed_seconds, rounded_minutes * 60.0, atol=1e-6, rtol=0):
        raise ConversionError(
            "GRIB1 cannot preserve this sub-minute model time under the selected encoding"
        )
    return parse_epoch(epoch) + timedelta(minutes=rounded_minutes)
