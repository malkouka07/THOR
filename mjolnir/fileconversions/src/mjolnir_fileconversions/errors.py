"""Domain-specific exceptions with stable command-line meanings."""


class ConversionError(RuntimeError):
    """Base class for a controlled conversion failure."""


class InputClassificationError(ConversionError):
    """Raised when an input is not a verified Mjolnir-processed product."""


class ScientificMappingError(ConversionError):
    """Raised when a requested physical mapping is not justified."""


class PressureEncodingError(ConversionError):
    """Raised when a pressure cannot be represented under the requested policy."""


class UnsupportedMessageError(ConversionError):
    """Raised when a GRIB2 message has no explicit GRIB1 mapping."""
