"""Machine-readable reports with mandatory authorship/review headers."""

from __future__ import annotations

import csv
import math
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


def with_difference_summary_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    group_fields: Sequence[str] = (),
    variable_field: str = "variable",
    units_field: str = "units",
    maximum_field: str = "maximum_absolute_difference",
    mean_field: str = "mean_absolute_difference",
    count_field: str = "compared_point_count",
    row_type_field: str = "row_type",
) -> list[dict[str, object]]:
    """Return copied detail rows followed by point-weighted summary rows.

    Summaries are always separated by variable and units, then by any
    caller-supplied fields such as ``stage`` or ``region``.  The summary mean
    is calculated from each detail row's point count, rather than as a
    potentially biased mean of per-row means.

    The input mappings are never modified.  All returned rows share one
    schema so that passing the result directly to :func:`write_csv` produces
    a valid, rectangular CSV file.
    """
    if not rows:
        return []

    grouping = tuple(
        dict.fromkeys((variable_field, units_field, *group_fields))
    )
    required = (*grouping, maximum_field, mean_field, count_field)
    if row_type_field in grouping:
        raise ValueError(f"{row_type_field!r} cannot be a summary group field")

    schema = [row_type_field]
    for row in rows:
        for field in row:
            if field not in schema:
                schema.append(field)
    for field in required:
        if field not in schema:
            schema.append(field)

    details: list[dict[str, object]] = []
    aggregates: dict[
        tuple[object, ...], dict[str, float | int | None]
    ] = {}
    for row_index, row in enumerate(rows, start=1):
        missing = [field for field in required if field not in row]
        if missing:
            raise ValueError(
                f"difference detail row {row_index} is missing fields: {missing}"
            )
        if str(row.get(row_type_field, "detail")).lower() == "summary":
            raise ValueError(
                "with_difference_summary_rows expects detail rows only"
            )

        detail = {field: row.get(field, "") for field in schema}
        detail[row_type_field] = "detail"
        details.append(detail)

        try:
            count_number = float(row[count_field])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"difference detail row {row_index} has a non-numeric "
                f"{count_field}: {row[count_field]!r}"
            ) from exc
        if (
            not math.isfinite(count_number)
            or count_number < 0
            or not count_number.is_integer()
        ):
            raise ValueError(
                f"difference detail row {row_index} has an invalid "
                f"{count_field}: {row[count_field]!r}"
            )
        count = int(count_number)

        key = tuple(row[field] for field in grouping)
        aggregate = aggregates.setdefault(
            key,
            {"count": 0, "weighted_absolute_sum": 0.0, "maximum": None},
        )
        if count == 0:
            continue

        try:
            maximum = float(row[maximum_field])
            mean = float(row[mean_field])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"difference detail row {row_index} has non-numeric "
                "difference statistics"
            ) from exc
        if (
            not math.isfinite(maximum)
            or not math.isfinite(mean)
            or maximum < 0
            or mean < 0
        ):
            raise ValueError(
                f"difference detail row {row_index} has invalid absolute "
                "difference statistics"
            )
        aggregate["count"] = int(aggregate["count"]) + count
        aggregate["weighted_absolute_sum"] = (
            float(aggregate["weighted_absolute_sum"]) + mean * count
        )
        prior_maximum = aggregate["maximum"]
        aggregate["maximum"] = (
            maximum
            if prior_maximum is None
            else max(float(prior_maximum), maximum)
        )

    summaries: list[dict[str, object]] = []
    for key, aggregate in aggregates.items():
        summary = {field: "" for field in schema}
        summary[row_type_field] = "summary"
        summary.update(zip(grouping, key))
        count = int(aggregate["count"])
        summary[count_field] = count
        if count:
            summary[maximum_field] = float(aggregate["maximum"])
            summary[mean_field] = (
                float(aggregate["weighted_absolute_sum"]) / count
            )
        else:
            summary[maximum_field] = float("nan")
            summary[mean_field] = float("nan")
        summaries.append(summary)

    return [*details, *summaries]


def write_difference_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    group_fields: Sequence[str] = (),
    variable_field: str = "variable",
    units_field: str = "units",
    maximum_field: str = "maximum_absolute_difference",
    mean_field: str = "mean_absolute_difference",
    count_field: str = "compared_point_count",
    row_type_field: str = "row_type",
) -> None:
    """Write detail differences plus schema-valid summary rows."""
    summarized = with_difference_summary_rows(
        rows,
        group_fields=group_fields,
        variable_field=variable_field,
        units_field=units_field,
        maximum_field=maximum_field,
        mean_field=mean_field,
        count_field=count_field,
        row_type_field=row_type_field,
    )
    write_csv(path, summarized)


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
