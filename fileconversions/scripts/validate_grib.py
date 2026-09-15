#!/usr/bin/env python3
"""Validate GRIB1 or GRIB2 structure and decoded fields."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _bootstrap  # noqa: F401
from mjolnir_fileconversions.commands import validate_command
from mjolnir_fileconversions.errors import ConversionError


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate GRIB structure, coordinates, parameters and values.")
    parser.add_argument("--input", type=Path, action="append")
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--input-glob")
    parser.add_argument("--edition", type=int, choices=(1, 2))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows = validate_command(args)
    except (ConversionError, FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0 if all(row["status"] == "passed" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
