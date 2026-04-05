#!/usr/bin/env python3

"""Merge fragmented THOR pressure-grid regrids into one canonical folder."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


PGRID_DIR_RE = re.compile(r"^pgrid_(\d+)_(\d+)(?:_(\d+))?$")
REGRID_FILE_RE = re.compile(r"^regrid_(.+)_(\d+)\.h5$")


@dataclass(frozen=True)
class FolderFile:
    """A regridded pressure file inside a pgrid folder."""

    index: int
    path: Path
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class PgridFolder:
    """A pgrid_* directory and the pressure-grid files it contains."""

    path: Path
    declared_start: int
    declared_end: int
    declared_stride: int | None
    files: dict[int, FolderFile]
    companion_txt: Path | None
    unknown_entries: tuple[str, ...]

    @property
    def actual_indices(self) -> list[int]:
        return sorted(self.files)

    @property
    def actual_start(self) -> int:
        return self.actual_indices[0]

    @property
    def actual_end(self) -> int:
        return self.actual_indices[-1]

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def actual_span(self) -> int:
        return self.actual_end - self.actual_start


@dataclass(frozen=True)
class Candidate:
    """A duplicate candidate for a single time index across pgrid folders."""

    folder: PgridFolder
    file: FolderFile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge fragmented pgrid_* folders into one canonical folder using the "
            "largest duplicate file for each index and report missing intervals."
        )
    )
    parser.add_argument("resultsf", help="Results directory containing pgrid_* folders")
    parser.add_argument(
        "-s",
        "--simulation-id",
        default="auto",
        help="Simulation ID used in regrid_<sim>_<index>.h5 names (default: auto-detect)",
    )
    parser.add_argument(
        "--delete-source-folders",
        action="store_true",
        help="Delete redundant source pgrid folders after a successful merge",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of hard-linking them into the merged folder",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without creating, replacing, or deleting files",
    )
    parser.add_argument(
        "--log-path",
        default=None,
        help="Optional path for the merge log (default: resultsf/pgrid_merge_<target>.log)",
    )
    return parser.parse_args()


def format_intervals(intervals: Iterable[tuple[int, int]]) -> str:
    chunks = []
    for start, end in intervals:
        if start == end:
            chunks.append(str(start))
        else:
            chunks.append(f"{start}-{end}")
    return ", ".join(chunks) if chunks else "none"


def collapse_indices(indices: Iterable[int]) -> list[tuple[int, int]]:
    ordered = sorted(set(indices))
    if not ordered:
        return []

    collapsed: list[tuple[int, int]] = []
    start = ordered[0]
    end = ordered[0]
    for value in ordered[1:]:
        if value == end + 1:
            end = value
            continue
        collapsed.append((start, end))
        start = value
        end = value
    collapsed.append((start, end))
    return collapsed


def find_missing_intervals(indices: Iterable[int]) -> list[tuple[int, int]]:
    ordered = sorted(set(indices))
    if len(ordered) < 2:
        return []

    missing: list[tuple[int, int]] = []
    previous = ordered[0]
    for current in ordered[1:]:
        if current - previous > 1:
            missing.append((previous + 1, current - 1))
        previous = current
    return missing


def summarize_declared_missing(folder: PgridFolder) -> list[tuple[int, int]]:
    if folder.declared_start > folder.declared_end:
        return []
    expected = range(folder.declared_start, folder.declared_end + 1)
    missing = [idx for idx in expected if idx not in folder.files]
    return collapse_indices(missing)


def choose_stride(folders: list[PgridFolder]) -> tuple[int, str]:
    declared = [folder.declared_stride for folder in folders if folder.declared_stride is not None]
    if not declared:
        return 1, "defaulted to stride 1 because the source folders use legacy names"

    counts = Counter(declared)
    stride, count = counts.most_common(1)[0]
    if len(counts) == 1:
        return stride, f"all source folders use stride {stride}"

    return stride, (
        f"selected stride {stride} as the most common declared stride "
        f"({count} of {len(declared)} folders)"
    )


def parse_folder_name(path: Path) -> tuple[int, int, int | None] | None:
    match = PGRID_DIR_RE.match(path.name)
    if not match:
        return None
    start, end, stride = match.groups()
    return int(start), int(end), None if stride is None else int(stride)


def load_text_file(path: Path) -> np.ndarray:
    return np.loadtxt(path, usecols=1)


def compare_pgrid_text(reference: Path, other: Path) -> str:
    ref_values = load_text_file(reference)
    other_values = load_text_file(other)
    if ref_values.shape != other_values.shape:
        return f"incompatible shape {ref_values.shape} vs {other_values.shape}"

    abs_diff = np.max(np.abs(ref_values - other_values))
    with np.errstate(divide="ignore", invalid="ignore"):
        rel_diff = np.max(
            np.where(ref_values != 0, np.abs((ref_values - other_values) / ref_values), 0.0)
        )
    return f"max_abs_diff={abs_diff:.6g}, max_rel_diff={rel_diff:.6g}"


def discover_pgrid_folders(resultsf: Path, simulation_id: str) -> tuple[list[PgridFolder], str]:
    raw_records: list[tuple[Path, int, int, int | None, list[tuple[str, FolderFile]], tuple[str, ...]]] = []
    discovered_sim_ids: set[str] = set()

    for child in sorted(resultsf.iterdir()):
        if not child.is_dir():
            continue
        parsed = parse_folder_name(child)
        if parsed is None:
            continue

        start, end, stride = parsed
        matches: list[tuple[str, FolderFile]] = []
        unknown_entries: list[str] = []

        for entry in sorted(child.iterdir()):
            if not entry.is_file():
                unknown_entries.append(entry.name)
                continue
            match = REGRID_FILE_RE.match(entry.name)
            if match is None:
                unknown_entries.append(entry.name)
                continue
            sim_id, index_text = match.groups()
            stat = entry.stat()
            matches.append(
                (
                    sim_id,
                    FolderFile(
                        index=int(index_text),
                        path=entry,
                        size=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                    ),
                )
            )
            discovered_sim_ids.add(sim_id)

        if matches:
            raw_records.append((child, start, end, stride, matches, tuple(unknown_entries)))

    if not raw_records:
        raise FileNotFoundError(f'No pgrid_* folders with regrid files were found in "{resultsf}"')

    if simulation_id == "auto":
        if len(discovered_sim_ids) != 1:
            found = ", ".join(sorted(discovered_sim_ids)) or "none"
            raise ValueError(
                "Could not auto-detect a unique simulation ID from regrid files. "
                f"Found: {found}. Use --simulation-id."
            )
        simulation_id = next(iter(discovered_sim_ids))

    text_files = {path.stem: path for path in resultsf.glob("pgrid_*.txt")}
    folders: list[PgridFolder] = []

    for path, start, end, stride, matches, unknown_entries in raw_records:
        files = {
            folder_file.index: folder_file
            for sim_id, folder_file in matches
            if sim_id == simulation_id
        }
        if not files:
            continue

        companion_txt = text_files.get(path.name)
        if companion_txt is None and stride is None:
            wildcard = list(resultsf.glob(f"pgrid_{start}_{end}_*.txt"))
            if len(wildcard) == 1:
                companion_txt = wildcard[0]

        folders.append(
            PgridFolder(
                path=path,
                declared_start=start,
                declared_end=end,
                declared_stride=stride,
                files=files,
                companion_txt=companion_txt,
                unknown_entries=unknown_entries,
            )
        )

    if not folders:
        raise FileNotFoundError(
            f'No pgrid_* folders containing regrid_{simulation_id}_*.h5 were found in "{resultsf}"'
        )

    return folders, simulation_id


def choose_reference_txt(
    folders: list[PgridFolder],
    target_path: Path,
    target_start: int,
    target_end: int,
) -> Path | None:
    for folder in folders:
        if folder.path == target_path and folder.companion_txt is not None:
            return folder.companion_txt

    coverage_matches = [
        folder
        for folder in folders
        if folder.companion_txt is not None
        and folder.actual_start == target_start
        and folder.actual_end == target_end
    ]
    if not coverage_matches:
        return None

    return max(
        coverage_matches,
        key=lambda folder: (
            folder.file_count,
            folder.declared_end - folder.declared_start,
            folder.path.name,
        ),
    ).companion_txt


def build_duplicate_map(folders: list[PgridFolder]) -> dict[int, list[Candidate]]:
    duplicates: dict[int, list[Candidate]] = defaultdict(list)
    for folder in folders:
        for index, folder_file in folder.files.items():
            duplicates[index].append(Candidate(folder=folder, file=folder_file))
    return duplicates


def choose_best_candidate(
    candidates: list[Candidate],
    target_path: Path,
) -> Candidate:
    def score(candidate: Candidate) -> tuple[int, int, int, int, int, str]:
        return (
            candidate.file.size,
            1 if candidate.folder.path == target_path else 0,
            candidate.folder.file_count,
            candidate.folder.actual_span,
            candidate.file.mtime_ns,
            str(candidate.file.path),
        )

    return max(candidates, key=score)


def hardlink_or_copy(source: Path, destination: Path, copy_only: bool) -> str:
    if copy_only:
        shutil.copy2(source, destination)
        return "copied"

    try:
        os.link(source, destination)
        return "hardlinked"
    except OSError:
        shutil.copy2(source, destination)
        return "copied"


def render_folder_summary(folder: PgridFolder) -> str:
    stride = folder.declared_stride if folder.declared_stride is not None else "legacy"
    missing_declared = summarize_declared_missing(folder)
    extras = ", ".join(folder.unknown_entries) if folder.unknown_entries else "none"
    return (
        f"{folder.path.name}: declared={folder.declared_start}-{folder.declared_end} "
        f"(stride={stride}), actual={folder.actual_start}-{folder.actual_end}, "
        f"files={folder.file_count}, missing_in_declared={format_intervals(missing_declared)}, "
        f"other_entries={extras}"
    )


def main() -> int:
    args = parse_args()
    resultsf = Path(args.resultsf).expanduser().resolve()
    if not resultsf.is_dir():
        raise NotADirectoryError(f'"{resultsf}" is not a directory')

    folders, simulation_id = discover_pgrid_folders(resultsf, args.simulation_id)
    all_indices = sorted({index for folder in folders for index in folder.files})
    target_start = all_indices[0]
    target_end = all_indices[-1]
    target_stride, stride_reason = choose_stride(folders)
    target_stem = f"pgrid_{target_start}_{target_end}_{target_stride}"
    target_path = resultsf / target_stem
    target_txt = resultsf / f"{target_stem}.txt"

    duplicates = build_duplicate_map(folders)
    chosen_by_index = {
        index: choose_best_candidate(candidates, target_path)
        for index, candidates in duplicates.items()
    }

    reference_txt = choose_reference_txt(folders, target_path, target_start, target_end)
    merged_missing = find_missing_intervals(all_indices)

    create_count = 0
    replace_count = 0
    keep_count = 0
    duplicate_count = 0
    action_lines: list[str] = []

    for index in sorted(chosen_by_index):
        chosen = chosen_by_index[index]
        candidates = duplicates[index]
        destination = target_path / chosen.file.path.name

        if len(candidates) > 1:
            duplicate_count += 1
            kept = f"{chosen.file.path} ({chosen.file.size} B)"
            dropped = ", ".join(
                f"{candidate.file.path} ({candidate.file.size} B)"
                for candidate in sorted(candidates, key=lambda item: item.file.size, reverse=True)[1:]
            )
            action_lines.append(f"duplicate {index}: keep {kept}; discard smaller copies {dropped}")

        if destination.exists():
            destination_stat = destination.stat()
            if destination.samefile(chosen.file.path):
                keep_count += 1
            elif destination_stat.st_size < chosen.file.size:
                replace_count += 1
                action_lines.append(
                    f"replace {destination} ({destination_stat.st_size} B) "
                    f"with {chosen.file.path} ({chosen.file.size} B)"
                )
            else:
                keep_count += 1
        else:
            create_count += 1
            action_lines.append(f"create {destination} from {chosen.file.path} ({chosen.file.size} B)")

    delete_lines: list[str] = []
    folders_to_delete: list[PgridFolder] = []
    txts_to_delete: list[Path] = []
    if args.delete_source_folders:
        for folder in folders:
            if folder.path == target_path:
                continue
            folders_to_delete.append(folder)
            delete_lines.append(f"delete folder {folder.path}")
            if folder.companion_txt is not None and folder.companion_txt != target_txt:
                txts_to_delete.append(folder.companion_txt)
                delete_lines.append(f"delete companion text {folder.companion_txt}")

    log_lines = [
        f"Results directory: {resultsf}",
        f"Simulation ID: {simulation_id}",
        f"Mode: {'dry-run' if args.dry_run else 'apply'}",
        f"Source folders: {len(folders)}",
        *[f"  - {render_folder_summary(folder)}" for folder in folders],
        f"Merged target folder: {target_path}",
        f"Merged target text: {target_txt}",
        f"Target stride: {target_stride} ({stride_reason})",
        (
            f"Reference pgrid text: {reference_txt}"
            if reference_txt is not None
            else "Reference pgrid text: none available"
        ),
    ]

    if reference_txt is not None:
        for folder in folders:
            if folder.companion_txt is None:
                log_lines.append(f"pgrid text compare {folder.path.name}: missing companion txt")
                continue
            if folder.companion_txt == reference_txt:
                log_lines.append(f"pgrid text compare {folder.path.name}: reference file")
                continue
            log_lines.append(
                f"pgrid text compare {folder.path.name}: "
                f"{compare_pgrid_text(reference_txt, folder.companion_txt)}"
            )

    log_lines.extend(
        [
            f"Covered indices: {target_start}-{target_end}",
            f"Missing merged intervals: {format_intervals(merged_missing)}",
            f"Duplicate indices resolved: {duplicate_count}",
            f"Planned file actions: create={create_count}, replace={replace_count}, keep={keep_count}",
        ]
    )
    log_lines.extend(action_lines)
    if args.delete_source_folders:
        log_lines.extend(delete_lines)
    else:
        log_lines.append("Source folders kept in place (use --delete-source-folders to remove them).")

    log_path = (
        Path(args.log_path).expanduser().resolve()
        if args.log_path is not None
        else resultsf / f"pgrid_merge_{target_stem}.log"
    )

    if not args.dry_run:
        target_path.mkdir(exist_ok=True)
        for chosen in chosen_by_index.values():
            destination = target_path / chosen.file.path.name
            if destination.exists():
                if destination.samefile(chosen.file.path):
                    continue
                if destination.stat().st_size >= chosen.file.size:
                    continue
                destination.unlink()
            hardlink_or_copy(chosen.file.path, destination, copy_only=args.copy)

        if reference_txt is not None and reference_txt != target_txt:
            shutil.copy2(reference_txt, target_txt)

        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

        if args.delete_source_folders:
            for folder in folders_to_delete:
                shutil.rmtree(folder.path)
            for txt_file in txts_to_delete:
                if txt_file.exists():
                    txt_file.unlink()
    elif args.log_path is not None:
        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print(f"Simulation ID: {simulation_id}")
    print(f"Source folders: {len(folders)}")
    print(f"Merged target: {target_path}")
    print(f"Missing merged intervals: {format_intervals(merged_missing)}")
    print(f"Duplicate indices resolved: {duplicate_count}")
    print(f"Planned file actions: create={create_count}, replace={replace_count}, keep={keep_count}")
    if args.delete_source_folders:
        print(f"Source folders to delete: {len(folders_to_delete)}")
    print(f"Log path: {log_path}")
    if args.dry_run:
        print("Dry run only: no files were changed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
