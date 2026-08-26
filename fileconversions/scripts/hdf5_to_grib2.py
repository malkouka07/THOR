#!/usr/bin/env python3
"""Migrated GRIB2 flow using the exact same canonical fields as GRIB1."""

from __future__ import annotations

import sys

import _bootstrap  # noqa: F401
from hdf5_to_grib1 import parser
from mjolnir_fileconversions.cli import parse_args_with_config
from mjolnir_fileconversions.commands import convert_hdf5
from mjolnir_fileconversions.errors import ConversionError


def main() -> int:
    try:
        args = parse_args_with_config(parser(default_pressure_level_policy="source"))
        convert_hdf5(args, edition=2)
    except (ConversionError, FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
