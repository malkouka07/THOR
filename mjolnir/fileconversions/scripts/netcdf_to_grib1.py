#!/usr/bin/env python3
"""Convert CF-like NetCDF pressure-grid winds to GRIB Edition 1."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _bootstrap  # noqa: F401
from mjolnir_fileconversions.cli import parse_args_with_config
from mjolnir_fileconversions.commands import convert_netcdf
from mjolnir_fileconversions.errors import ConversionError


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Convert CF-like NetCDF to controlled GRIB Edition 1.")
    result.add_argument("--input", type=Path, action="append")
    result.add_argument("--input-dir", type=Path)
    result.add_argument("--input-glob")
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--config", type=Path)
    result.add_argument("--variables", nargs="+", default=["u", "v", "omega"])
    result.add_argument("--time-index", type=int)
    result.add_argument("--time-indices", nargs="*", type=int)
    result.add_argument("--test-mode", action="store_true")
    result.add_argument("--max-files", type=int)
    result.add_argument("--lat-step", type=float, default=4.0)
    result.add_argument("--lon-step", type=float, default=4.0)
    result.add_argument("--longitude-convention", choices=("0-360",), default="0-360")
    result.add_argument("--regrid", choices=("never", "if-needed", "always"), default="if-needed")
    result.add_argument(
        "--pressure-level-policy",
        choices=("source", "hpa-aligned"),
        default="hpa-aligned",
        help="derive exact integer-hPa targets with log-pressure interpolation (default)",
    )
    result.add_argument("--level-encoding", choices=("strict", "hpa-rounded", "ecmwf-pa"), default="strict")
    result.add_argument("--max-level-absolute-error-pa", type=float, default=50.0)
    result.add_argument("--max-level-relative-error", type=float, default=0.001)
    result.add_argument("--vertical-velocity-mode", choices=("strict", "native-omega", "model-defined", "hydrostatic", "omit"), default="strict")
    result.add_argument("--gravity", type=float, help="Verified planet gravity for explicit hydrostatic omega mode.")
    result.add_argument("--file-layout", choices=("per-variable", "per-time", "combined"), default="per-variable")
    result.add_argument("--technical-epoch", default="2000-01-01T00:00:00Z")
    result.add_argument("--bits-per-value", type=int, default=24)
    result.add_argument("--overwrite", action="store_true")
    result.add_argument("--keep-intermediate", action="store_true")
    result.add_argument("--log-level", default="INFO")
    result.add_argument("--log-file", type=Path)
    return result


def main() -> int:
    try:
        args = parse_args_with_config(parser())
        convert_netcdf(args)
    except (ConversionError, FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
