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


def test_percentage_summary_uses_pooled_reference_scales_and_counts():
    rows = [
        {
            "variable": "eastward_wind",
            "units": "m s-1",
            "maximum_absolute_difference": 1.0,
            "mean_absolute_difference": 1.0,
            "compared_point_count": 1,
            "reference_maximum_absolute_value": 1.0,
            "reference_mean_absolute_value": 1.0,
            "absolute_difference_sum": 1.0,
            "reference_absolute_value_sum": 1.0,
        },
        {
            "variable": "eastward_wind",
            "units": "m s-1",
            "maximum_absolute_difference": 3.0,
            "mean_absolute_difference": 3.0,
            "compared_point_count": 9,
            "reference_maximum_absolute_value": 100.0,
            "reference_mean_absolute_value": 100.0,
            "absolute_difference_sum": 27.0,
            "reference_absolute_value_sum": 900.0,
        },
    ]

    result = with_difference_summary_rows(
        rows,
        reference_maximum_field="reference_maximum_absolute_value",
        reference_mean_field="reference_mean_absolute_value",
        difference_sum_field="absolute_difference_sum",
        reference_sum_field="reference_absolute_value_sum",
    )
    first, second, summary = result

    maximum_percentage = (
        "maximum_absolute_difference_percent_of_reference_maximum"
    )
    mean_percentage = (
        "mean_absolute_difference_percent_of_reference_mean_absolute"
    )
    assert first[maximum_percentage] == ""
    assert second[maximum_percentage] == ""
    assert summary["maximum_absolute_difference"] == 3.0
    assert summary["reference_maximum_absolute_value"] == 100.0
    # The footer is global max(error) / global max(reference), not the
    # maximum of the two detail percentages (which would be 100%).
    assert summary[maximum_percentage] == pytest.approx(3.0)

    expected_difference_mean = (1.0 * 1 + 3.0 * 9) / 10
    expected_reference_mean = (1.0 * 1 + 100.0 * 9) / 10
    assert summary["mean_absolute_difference"] == pytest.approx(
        expected_difference_mean
    )
    assert summary["reference_mean_absolute_value"] == pytest.approx(
        expected_reference_mean
    )
    assert summary["absolute_difference_sum"] == pytest.approx(28.0)
    assert summary["reference_absolute_value_sum"] == pytest.approx(901.0)
    assert summary[mean_percentage] == pytest.approx(
        100.0 * expected_difference_mean / expected_reference_mean
    )


def test_percentage_of_exact_zero_reference_is_zero():
    rows = [
        {
            "variable": "omega",
            "units": "Pa s-1",
            "maximum_absolute_difference": 0.0,
            "mean_absolute_difference": 0.0,
            "compared_point_count": 12,
            "reference_maximum_absolute_value": 0.0,
            "reference_mean_absolute_value": 0.0,
        }
    ]

    result = with_difference_summary_rows(
        rows,
        reference_maximum_field="reference_maximum_absolute_value",
        reference_mean_field="reference_mean_absolute_value",
    )

    detail, summary = result
    assert detail["maximum_absolute_difference_percent_of_reference_maximum"] == ""
    assert detail["mean_absolute_difference_percent_of_reference_mean_absolute"] == ""
    assert (
        summary["maximum_absolute_difference_percent_of_reference_maximum"]
        == 0.0
    )
    assert (
        summary["mean_absolute_difference_percent_of_reference_mean_absolute"]
        == 0.0
    )


def test_percentage_of_nonzero_error_against_zero_reference_is_nan():
    rows = [
        {
            "variable": "omega",
            "units": "Pa s-1",
            "maximum_absolute_difference": 0.2,
            "mean_absolute_difference": 0.1,
            "compared_point_count": 12,
            "reference_maximum_absolute_value": 0.0,
            "reference_mean_absolute_value": 0.0,
        }
    ]

    result = with_difference_summary_rows(
        rows,
        reference_maximum_field="reference_maximum_absolute_value",
        reference_mean_field="reference_mean_absolute_value",
    )

    detail, summary = result
    assert detail["maximum_absolute_difference_percent_of_reference_maximum"] == ""
    assert detail["mean_absolute_difference_percent_of_reference_mean_absolute"] == ""
    assert math.isnan(
        summary["maximum_absolute_difference_percent_of_reference_maximum"]
    )
    assert math.isnan(
        summary["mean_absolute_difference_percent_of_reference_mean_absolute"]
    )


@pytest.mark.parametrize(
    "configured",
    [
        {"reference_maximum_field": "reference_maximum_absolute_value"},
        {"reference_mean_field": "reference_mean_absolute_value"},
    ],
)
def test_percentage_reference_fields_must_be_configured_together(configured):
    rows = [
        {
            "variable": "air_temperature",
            "units": "K",
            "maximum_absolute_difference": 1.0,
            "mean_absolute_difference": 0.5,
            "compared_point_count": 3,
            "reference_maximum_absolute_value": 280.0,
            "reference_mean_absolute_value": 270.0,
        }
    ]

    with pytest.raises(ValueError, match="must be configured together"):
        with_difference_summary_rows(rows, **configured)


def test_percentage_csv_footer_uses_same_rectangular_schema(tmp_path):
    rows = [
        {
            "variable": "air_temperature",
            "units": "K",
            "time": "t0",
            "maximum_absolute_difference": 0.4,
            "mean_absolute_difference": 0.2,
            "compared_point_count": 5,
            "reference_maximum_absolute_value": 300.0,
            "reference_mean_absolute_value": 250.0,
        }
    ]
    path = tmp_path / "percentage_differences.csv"

    write_difference_csv(
        path,
        rows,
        reference_maximum_field="reference_maximum_absolute_value",
        reference_mean_field="reference_mean_absolute_value",
    )

    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        written = list(reader)
    assert len(written) == 2
    assert [row["row_type"] for row in written] == ["detail", "summary"]
    assert (
        "maximum_absolute_difference_percent_of_reference_maximum"
        in reader.fieldnames
    )
    assert (
        "mean_absolute_difference_percent_of_reference_mean_absolute"
        in reader.fieldnames
    )
    assert float(
        written[-1][
            "maximum_absolute_difference_percent_of_reference_maximum"
        ]
    ) == pytest.approx(100.0 * 0.4 / 300.0)
    assert float(
        written[-1][
            "mean_absolute_difference_percent_of_reference_mean_absolute"
        ]
    ) == pytest.approx(100.0 * 0.2 / 250.0)
