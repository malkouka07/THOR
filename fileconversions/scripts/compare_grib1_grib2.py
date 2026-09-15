#!/usr/bin/env python3
"""Compare decoded GRIB1 and GRIB2 fields numerically."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _bootstrap  # noqa: F401
from mjolnir_fileconversions.commands import compare_command
from mjolnir_fileconversions.errors import ConversionError


def main() -> int:
    parser = argparse.ArgumentParser(description="Numerically compare GRIB1 and GRIB2 writer outputs.")
    parser.add_argument("--grib1-dir", type=Path, required=True)
    parser.add_argument("--grib2-dir", type=Path, required=True)
    parser.add_argument("--grib1-glob", default="*.grib1")
    parser.add_argument("--grib2-glob", default="*.grib2")
    parser.add_argument("--packing-tolerance", type=float, default=1e-4)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows = compare_command(args)
    except (ConversionError, FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0 if all(row["parity_status"] == "passed" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
