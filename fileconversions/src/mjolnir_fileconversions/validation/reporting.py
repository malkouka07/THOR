"""Machine-readable reports with mandatory authorship/review headers."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from ..models import ProcessingStage
from ..processing.pressure import PressureMapping
from ..writers.grib_common import EncodedLevel


REPORT_HEADER = (
    "Generated with OpenAI Codex assistance\n"
    "Review status: pending manual review by Márkó\n"
)


def write_csv(path: Path, rows: Sequence[Mapping[str, object]], fieldnames: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_pressure_mapping(
    path: Path,
    mappings: Sequence[PressureMapping],
    encoded: Sequence[EncodedLevel] | None = None,
    encoding_errors: Mapping[int, str] | None = None,
    compatibility_mode: str | None = None,
) -> None:
    by_requested = {item.requested_pa: item for item in encoded or []}
    rows: list[dict[str, object]] = []
    for item in mappings:
        row = item.as_dict()
        level = by_requested.get(item.target_level_pa)
        if level:
            encoding_note = (
                f"effective GRIB1 pressure {level.effective_pa} Pa; "
                f"encoding error {level.absolute_error_pa} Pa"
            )
            row.update(
                grib1_level_encoding=f"{level.type_of_level}:{level.encoded_level}",
                grib1_exactly_representable=level.absolute_error_pa == 0,
                compatibility_mode=level.mode,
                notes="; ".join(filter(None, (item.notes, encoding_note))),
            )
        elif encoding_errors and item.target_level_pa in encoding_errors:
            row.update(
                grib1_level_encoding="blocked before writer",
                grib1_exactly_representable=False,
                compatibility_mode=compatibility_mode or "unknown",
                notes="; ".join(
                    filter(None, (item.notes, encoding_errors[item.target_level_pa]))
                ),
            )
        rows.append(row)
    write_csv(path, rows, list(PressureMapping.__dataclass_fields__))


def write_processing_stages(path: Path, stages: Sequence[ProcessingStage]) -> None:
    write_csv(path, [stage.as_dict() for stage in stages], list(ProcessingStage.__dataclass_fields__))


def write_markdown_report(path: Path, title: str, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [f"# {title}", "", REPORT_HEADER.rstrip(), "", *lines, ""]
    path.write_text("\n".join(body), encoding="utf-8")
