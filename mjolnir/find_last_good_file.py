#!/usr/bin/env python3

"""Find the newest "good-sized" numbered file in a THOR results directory.

The script is generic: point it at any directory, and it will group files into
families based on the filename shape. For each numbered family, it learns the
typical file size and reports the newest file whose size still looks complete.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


NUMBER_RE = re.compile(r"\d+")


@dataclass(frozen=True)
class FileEntry:
    path: str
    name: str
    size: int
    numbers: tuple[int, ...]


@dataclass(frozen=True)
class FamilyReport:
    family: str
    file_count: int
    typical_size: int
    cutoff_size: int
    last_good_file: str | None
    last_good_size: int | None
    trailing_suspect_files: int
    first_trailing_suspect: str | None
    first_trailing_suspect_size: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find the newest good-sized numbered file in a directory. "
            "Files are grouped by filename shape, for example "
            "'esp_output_venus_#.h5' or 'regrid_height_venus_#.h5'."
        )
    )
    parser.add_argument(
        "directory",
        help="Directory to scan.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan subdirectories too.",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include dotfiles.",
    )
    parser.add_argument(
        "--min-files",
        type=int,
        default=5,
        help="Minimum files needed before a family is reported. Default: 5.",
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=1_000_000,
        help=(
            "Ignore families whose typical file size is smaller than this many bytes. "
            "Default: 1000000."
        ),
    )
    parser.add_argument(
        "--ratio",
        type=float,
        default=0.98,
        help=(
            "Minimum fraction of the typical size for a file to count as good. "
            "Default: 0.98."
        ),
    )
    parser.add_argument(
        "--all-families",
        action="store_true",
        help="Show every numbered family, even tiny support files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    return parser.parse_args()


def iter_files(root: Path, recursive: bool, include_hidden: bool) -> Iterable[Path]:
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            if not include_hidden:
                dirnames[:] = [name for name in dirnames if not name.startswith(".")]
            for filename in filenames:
                if include_hidden or not filename.startswith("."):
                    yield Path(dirpath) / filename
        return

    for child in root.iterdir():
        if child.is_file() and (include_hidden or not child.name.startswith(".")):
            yield child


def split_matchable_name(name: str) -> tuple[str, str]:
    base, dot, tail = name.rpartition(".")
    if dot and any(char.isalpha() for char in tail):
        return base, f".{tail}"
    return name, ""


def family_key(name: str) -> str | None:
    matchable, extension = split_matchable_name(name)
    if not NUMBER_RE.search(matchable):
        return None
    return NUMBER_RE.sub("#", matchable) + extension


def numbers_from_name(name: str) -> tuple[int, ...]:
    matchable, _ = split_matchable_name(name)
    return tuple(int(value) for value in NUMBER_RE.findall(matchable))


def human_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "-"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    units = ["KiB", "MiB", "GiB", "TiB"]
    value = float(size_bytes)
    for unit in units:
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.2f} {unit}"
    return f"{value:.2f} PiB"


def compute_cutoff(sizes: list[int], ratio: float) -> tuple[int, int]:
    typical = int(statistics.median(sizes))
    deviations = [abs(size - typical) for size in sizes]
    mad = int(statistics.median(deviations)) if deviations else 0

    ratio_cutoff = int(math.floor(typical * ratio))
    if mad == 0:
        cutoff = ratio_cutoff
    else:
        cutoff = max(ratio_cutoff, typical - (6 * mad))

    return typical, cutoff


def analyze_family(entries: list[FileEntry], ratio: float) -> FamilyReport:
    sizes = [entry.size for entry in entries]
    typical, cutoff = compute_cutoff(sizes, ratio)

    sorted_entries = sorted(entries, key=lambda entry: (entry.numbers, entry.name))
    last_good: FileEntry | None = None
    trailing_suspects: list[FileEntry] = []

    for entry in reversed(sorted_entries):
        if entry.size >= cutoff:
            last_good = entry
            break
        trailing_suspects.append(entry)

    first_trailing = trailing_suspects[-1] if trailing_suspects else None

    return FamilyReport(
        family=family_key(sorted_entries[0].name) or sorted_entries[0].name,
        file_count=len(entries),
        typical_size=typical,
        cutoff_size=cutoff,
        last_good_file=last_good.path if last_good else None,
        last_good_size=last_good.size if last_good else None,
        trailing_suspect_files=len(trailing_suspects),
        first_trailing_suspect=first_trailing.path if first_trailing else None,
        first_trailing_suspect_size=first_trailing.size if first_trailing else None,
    )


def build_reports(
    directory: Path,
    recursive: bool,
    include_hidden: bool,
    min_files: int,
    min_size: int,
    ratio: float,
    show_all_families: bool,
) -> list[FamilyReport]:
    families: dict[str, list[FileEntry]] = defaultdict(list)

    for file_path in iter_files(directory, recursive=recursive, include_hidden=include_hidden):
        key = family_key(file_path.name)
        if key is None:
            continue

        try:
            size = file_path.stat().st_size
        except OSError:
            continue

        families[key].append(
            FileEntry(
                path=str(file_path),
                name=file_path.name,
                size=size,
                numbers=numbers_from_name(file_path.name),
            )
        )

    reports: list[FamilyReport] = []
    for entries in families.values():
        if len(entries) < max(2, min_files):
            if not show_all_families:
                continue
        report = analyze_family(entries, ratio=ratio)
        if not show_all_families and report.typical_size < min_size:
            continue
        reports.append(report)

    reports.sort(
        key=lambda report: (
            report.file_count,
            report.typical_size,
            report.last_good_file or "",
        ),
        reverse=True,
    )
    return reports


def choose_recommended_report(reports: list[FamilyReport]) -> FamilyReport | None:
    if not reports:
        return None
    return max(reports, key=lambda report: (report.file_count, report.typical_size))


def print_text(directory: Path, reports: list[FamilyReport]) -> int:
    print(f"Directory: {directory}")
    print()

    if not reports:
        print("No numbered file families matched the current filters.")
        print("Try lowering --min-size, using --all-families, or checking the path.")
        return 1

    recommended = choose_recommended_report(reports)
    if recommended and recommended.last_good_file:
        print(f"Recommended last good file: {recommended.last_good_file}")
        print(f"Recommended family: {recommended.family}")
        print()

    for report in reports:
        print(f"Family: {report.family}")
        print(f"  Files seen: {report.file_count}")
        print(
            f"  Typical size: {human_size(report.typical_size)} "
            f"({report.typical_size} bytes)"
        )
        print(
            f"  Good-size cutoff: {human_size(report.cutoff_size)} "
            f"({report.cutoff_size} bytes)"
        )
        if report.last_good_file:
            print(f"  Last good file: {report.last_good_file}")
            print(
                f"  Last good size: {human_size(report.last_good_size)} "
                f"({report.last_good_size} bytes)"
            )
        else:
            print("  Last good file: none found")
        print(f"  Trailing suspect files: {report.trailing_suspect_files}")
        if report.first_trailing_suspect:
            print(
                f"  First trailing suspect: {report.first_trailing_suspect} "
                f"({human_size(report.first_trailing_suspect_size)})"
            )
        print()

    return 0


def print_json(directory: Path, reports: list[FamilyReport]) -> int:
    payload = {
        "directory": str(directory),
        "recommended": asdict(choose_recommended_report(reports))
        if reports
        else None,
        "families": [asdict(report) for report in reports],
    }
    print(json.dumps(payload, indent=2))
    return 0 if reports else 1


def main() -> int:
    args = parse_args()
    directory = Path(args.directory).expanduser().resolve()

    if not directory.exists():
        print(f"Directory does not exist: {directory}", file=sys.stderr)
        return 2
    if not directory.is_dir():
        print(f"Path is not a directory: {directory}", file=sys.stderr)
        return 2
    if not 0.0 < args.ratio <= 1.0:
        print("--ratio must be greater than 0 and at most 1.", file=sys.stderr)
        return 2
    if args.min_files < 2:
        print("--min-files must be at least 2.", file=sys.stderr)
        return 2
    if args.min_size < 0:
        print("--min-size must be zero or greater.", file=sys.stderr)
        return 2

    reports = build_reports(
        directory=directory,
        recursive=args.recursive,
        include_hidden=args.include_hidden,
        min_files=args.min_files,
        min_size=args.min_size,
        ratio=args.ratio,
        show_all_families=args.all_families,
    )

    if args.json:
        return print_json(directory, reports)
    return print_text(directory, reports)


if __name__ == "__main__":
    raise SystemExit(main())
