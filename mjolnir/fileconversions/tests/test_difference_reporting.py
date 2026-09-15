import csv
import math
from copy import deepcopy

import pytest

from mjolnir_fileconversions.validation.reporting import (
    with_difference_summary_rows,
    write_difference_csv,
)


def test_difference_summaries_are_weighted_grouped_and_non_mutating():
    rows = [
        {
            "variable": "eastward_wind",
            "units": "m s-1",
            "region": "all",
            "time": "t0",
            "maximum_absolute_difference": 2.0,
            "mean_absolute_difference": 1.0,
            "compared_point_count": 2,
        },
        {
            "variable": "eastward_wind",
            "units": "m s-1",
            "region": "all",
            "time": "t1",
            "maximum_absolute_difference": 5.0,
            "mean_absolute_difference": 3.0,
            "compared_point_count": 8,
        },
        {
            "variable": "northward_wind",
            "units": "m s-1",
            "region": "all",
            "time": "t0",
            "maximum_absolute_difference": 4.0,
            "mean_absolute_difference": 2.0,
            "compared_point_count": 3,
        },
    ]
    original = deepcopy(rows)

    result = with_difference_summary_rows(rows, group_fields=("region",))

    assert rows == original
    assert [row["row_type"] for row in result[:3]] == ["detail"] * 3
    assert [row["row_type"] for row in result[3:]] == ["summary"] * 2
    eastward = result[3]
    assert eastward["variable"] == "eastward_wind"
    assert eastward["units"] == "m s-1"
    assert eastward["region"] == "all"
    assert eastward["compared_point_count"] == 10
    assert eastward["maximum_absolute_difference"] == 5.0
    assert eastward["mean_absolute_difference"] == pytest.approx(2.6)
    assert eastward["time"] == ""


def test_difference_summaries_never_mix_units_or_optional_groups():
    rows = [
        {
            "variable": "temperature",
            "units": "K",
            "stage": "horizontal",
            "maximum_absolute_difference": 1.0,
            "mean_absolute_difference": 0.5,
            "compared_point_count": 4,
        },
        {
            "variable": "temperature",
            "units": "degC",
            "stage": "horizontal",
            "maximum_absolute_difference": 2.0,
            "mean_absolute_difference": 1.5,
            "compared_point_count": 4,
        },
        {
            "variable": "temperature",
            "units": "K",
            "stage": "vertical",
            "maximum_absolute_difference": 3.0,
            "mean_absolute_difference": 2.5,
            "compared_point_count": 4,
        },
    ]

    result = with_difference_summary_rows(rows, group_fields=("stage",))
    summaries = result[len(rows) :]

    assert [
        (row["variable"], row["units"], row["stage"])
        for row in summaries
    ] == [
        ("temperature", "K", "horizontal"),
        ("temperature", "degC", "horizontal"),
        ("temperature", "K", "vertical"),
    ]


def test_write_difference_csv_has_one_rectangular_schema(tmp_path):
    rows = [
        {
            "variable": "omega",
            "units": "Pa s-1",
            "time": "t0",
            "maximum_absolute_difference": 0.2,
            "mean_absolute_difference": 0.1,
            "compared_point_count": 5,
        },
        {
            "variable": "omega",
            "units": "Pa s-1",
            "time": "t1",
            "note": "later row has an extra column",
            "maximum_absolute_difference": 0.4,
            "mean_absolute_difference": 0.3,
            "compared_point_count": 5,
        },
    ]
    path = tmp_path / "differences.csv"

    write_difference_csv(path, rows)

    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        written = list(reader)
    assert reader.fieldnames == [
        "row_type",
        "variable",
        "units",
        "time",
        "maximum_absolute_difference",
        "mean_absolute_difference",
        "compared_point_count",
        "note",
    ]
    assert [row["row_type"] for row in written] == [
        "detail",
        "detail",
        "summary",
    ]
    assert written[-1]["note"] == ""
    assert float(written[-1]["maximum_absolute_difference"]) == 0.4
    assert float(written[-1]["mean_absolute_difference"]) == pytest.approx(0.2)


def test_zero_count_group_gets_explicit_empty_summary():
    rows = [
        {
            "variable": "temperature",
            "units": "K",
            "maximum_absolute_difference": float("nan"),
            "mean_absolute_difference": float("nan"),
            "compared_point_count": 0,
        }
    ]

    summary = with_difference_summary_rows(rows)[-1]

    assert summary["compared_point_count"] == 0
    assert math.isnan(summary["maximum_absolute_difference"])
    assert math.isnan(summary["mean_absolute_difference"])
