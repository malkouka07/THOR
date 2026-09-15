#!/usr/bin/env python3
"""Classify HDF5 files without converting or modifying source data."""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401
from mjolnir_fileconversions.discovery import classify_collection, write_classification_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify native, Mjolnir-processed, metadata and unknown HDF5 files.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--recursive", action="store_true")
    args = parser.parse_args()
    root = args.input_dir.expanduser().resolve()
    paths = sorted(root.rglob("*.h5") if args.recursive else root.glob("*.h5"))
    rows = classify_collection(paths)
    write_classification_csv(args.report.expanduser().resolve(), rows)
    for row in rows:
        print(f"{row.classification:20s} {row.file_path} — {row.reason}")
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
