"""Missing-value normalization."""

import numpy as np

from ..errors import ConversionError


def normalize_missing(values: np.ndarray, fill_values: list[float] | None = None) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64).copy()
    for fill in fill_values or []:
        result[np.isclose(result, fill, equal_nan=False)] = np.nan
    if np.any(np.isinf(result)):
        raise ConversionError("input contains Inf")
    return result
