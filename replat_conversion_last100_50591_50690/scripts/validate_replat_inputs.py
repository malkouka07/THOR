#!/usr/bin/env python3
"""Validate standardized THOR/RePLaT NetCDF files and optional GRIB2 files."""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import h5py
import numpy as np
import xarray as xr


EXPECTED_UNITS = {
    "eastward_wind": "m s-1",
    "northward_wind": "m s-1",
    "upward_air_velocity": "m s-1",
    "lagrangian_tendency_of_air_pressure": "Pa s-1",
}


@dataclass
class FileResult:
    path: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passes: list[str] = field(default_factory=list)
    stats: dict[str, dict[str, float]] = field(default_factory=dict)
    source_comparison: dict[str, dict[str, float]] = field(default_factory=dict)
    time_values: list[float] = field(default_factory=list)
    level_values: list[int] = field(default_factory=list)

    def check(self, condition: bool, success: str, failure: str) -> None:
        (self.passes if condition else self.errors).append(
            success if condition else failure
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate RePLaT-ready NetCDF and optional GRIB2 files."
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="Optional directory containing source regrid_height HDF5 files.",
    )
    parser.add_argument(
        "--grib-dir", type=Path, help="Optional directory containing matching GRIB2."
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Return failure when warnings are present.",
    )
    return parser.parse_args()


def finite_stats(array: np.ndarray) -> dict[str, float]:
    array = np.asarray(array, dtype=np.float64)
    return {
        "finite": int(np.isfinite(array).sum()),
        "total": int(array.size),
        "min": float(np.nanmin(array)),
        "max": float(np.nanmax(array)),
        "mean": float(np.nanmean(array)),
        "std": float(np.nanstd(array)),
    }


def area_weighted_mean(array: np.ndarray, latitude: np.ndarray) -> float:
    array = np.asarray(array, dtype=np.float64)
    weights = np.cos(np.deg2rad(latitude))[None, None, :, None]
    weights = np.broadcast_to(weights, array.shape)
    finite = np.isfinite(array)
    return float(
        np.sum(np.where(finite, array * weights, 0.0))
        / np.sum(np.where(finite, weights, 0.0))
    )


def source_area_weighted_mean(array: np.ndarray, latitude: np.ndarray) -> float:
    weights = np.cos(np.deg2rad(latitude))[:, None, None]
    weights = np.broadcast_to(weights, array.shape)
    finite = np.isfinite(array)
    return float(
        np.sum(np.where(finite, array * weights, 0.0))
        / np.sum(np.where(finite, weights, 0.0))
    )


def command_ok(command: list[str]) -> tuple[bool, str]:
    process = subprocess.run(
        command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    return process.returncode == 0, process.stdout.strip()


def compare_source(
    dataset: xr.Dataset, source_dir: Path, result: FileResult
) -> None:
    source_name = dataset.attrs.get("source_file")
    if not source_name:
        result.warnings.append("Nincs source_file globális attribútum.")
        return
    source_path = source_dir / str(source_name)
    if not source_path.is_file():
        result.warnings.append(f"A forrás-összehasonlítás fájlja nem található: {source_path}")
        return
    with h5py.File(source_path, "r") as handle:
        latitude = np.asarray(handle["Latitude"][...], dtype=np.float64)
        for output_name in EXPECTED_UNITS:
            if output_name not in dataset:
                continue
            source_variable = str(
                dataset[output_name].attrs.get("original_variable_name", "")
            )
            if source_variable not in handle:
                result.warnings.append(
                    f"{output_name}: az eredeti {source_variable!r} változó nem található."
                )
                continue
            source = np.asarray(handle[source_variable][...], dtype=np.float64)
            output = np.asarray(dataset[output_name].values, dtype=np.float64)
            source_stats = finite_stats(source)
            output_stats = finite_stats(output)
            source_mean = source_area_weighted_mean(source, latitude)
            output_mean = area_weighted_mean(
                output, np.asarray(dataset.latitude.values)
            )
            result.source_comparison[output_name] = {
                "source_area_mean": source_mean,
                "output_area_mean": output_mean,
                "normalized_mean_difference": abs(output_mean - source_mean)
                / max(source_stats["std"], 1e-12),
                "source_min": source_stats["min"],
                "output_min": output_stats["min"],
                "source_max": source_stats["max"],
                "output_max": output_stats["max"],
            }
            tolerance = max(1e-6, 1e-5 * max(abs(source_stats["min"]), abs(source_stats["max"])))
            if (
                output_stats["min"] < source_stats["min"] - tolerance
                or output_stats["max"] > source_stats["max"] + tolerance
            ):
                result.warnings.append(
                    f"{output_name}: a kimeneti szélsőérték kilép a forrás "
                    "tartományából (a vertikális koordináták eltérnek, ezért ez figyelmeztetés)."
                )
            if result.source_comparison[output_name]["normalized_mean_difference"] > 0.5:
                result.warnings.append(
                    f"{output_name}: a területsúlyozott átlag változása meghaladja "
                    "a forrás szórásának 0,5-szeresét."
                )


def validate_netcdf(path: Path, source_dir: Path | None) -> FileResult:
    result = FileResult(path)
    try:
        with xr.open_dataset(path, decode_times=False) as dataset:
            required_coords = {"time", "level", "latitude", "longitude"}
            result.check(
                required_coords.issubset(dataset.coords),
                "A négy kötelező koordináta megvan.",
                f"Hiányzó koordináta: {required_coords - set(dataset.coords)}",
            )
            required_vars = {"eastward_wind", "northward_wind"}
            result.check(
                required_vars.issubset(dataset.data_vars),
                "A két horizontális szélkomponens megvan.",
                f"Hiányzó horizontális szél: {required_vars - set(dataset.data_vars)}",
            )
            vertical = {
                "upward_air_velocity",
                "lagrangian_tendency_of_air_pressure",
            }.intersection(dataset.data_vars)
            result.check(
                len(vertical) == 1,
                "Pontosan egy, fizikailag azonosított vertikális sebesség van.",
                f"A vertikális sebesség változói nem egyértelműek: {vertical}",
            )
            if not required_coords.issubset(dataset.coords):
                return result

            latitude = np.asarray(dataset.latitude.values, dtype=np.float64)
            longitude = np.asarray(dataset.longitude.values, dtype=np.float64)
            level_raw = np.asarray(dataset.level.values)
            level = level_raw.astype(np.float64)
            result.time_values = np.asarray(dataset.time.values, dtype=float).tolist()
            result.level_values = level_raw.astype(int).tolist()

            result.check(
                latitude.size >= 2 and latitude[0] == -90.0 and latitude[-1] == 90.0,
                "A latitude pontosan -90°-tól 90°-ig tart.",
                f"Hibás szélességi végpont: {latitude[0]} .. {latitude[-1]}",
            )
            lat_diff = np.diff(latitude)
            result.check(
                np.all(lat_diff > 0)
                and np.allclose(lat_diff, lat_diff[0], rtol=0, atol=1e-10),
                "A latitude szigorúan növekvő és egyenletes.",
                "A latitude nem szigorúan növekvő vagy nem egyenletes.",
            )
            lon_diff = np.diff(longitude)
            periodic = (
                longitude.size >= 2
                and np.all(lon_diff > 0)
                and np.allclose(lon_diff, lon_diff[0], rtol=0, atol=1e-10)
                and math.isclose(
                    longitude[-1] + lon_diff[0] - longitude[0],
                    360.0,
                    abs_tol=1e-10,
                )
            )
            result.check(
                periodic,
                "A longitude egyenletes, növekvő és 360°-osan periodikus.",
                "A longitude nem egyenletes vagy nem zár periodikusan 360°-ra.",
            )
            integer_levels = np.issubdtype(level_raw.dtype, np.integer) and np.all(
                level == np.rint(level)
            )
            result.check(
                integer_levels
                and str(dataset.level.attrs.get("units", "")).lower() == "pa",
                "A nyomásszintek egész Pa értékek.",
                f"A level nem egész Pa: dtype={level_raw.dtype}, "
                f"units={dataset.level.attrs.get('units')!r}",
            )
            result.check(
                np.all(np.diff(level) < 0) or np.all(np.diff(level) > 0),
                "A nyomásszintek szigorúan monotonok.",
                "A nyomásszintek nem monotonok.",
            )

            expected_dims = ("time", "level", "latitude", "longitude")
            for name, variable in dataset.data_vars.items():
                if name not in EXPECTED_UNITS:
                    continue
                result.check(
                    variable.dims == expected_dims,
                    f"{name}: helyes dimenziósorrend.",
                    f"{name}: hibás dimenziósorrend {variable.dims}.",
                )
                values = np.asarray(variable.values)
                stat = finite_stats(values)
                stat["area_weighted_mean"] = area_weighted_mean(values, latitude)
                result.stats[name] = stat
                result.check(
                    stat["finite"] == stat["total"],
                    f"{name}: nincs NaN/Inf vagy hiányzó érték.",
                    f"{name}: {stat['total'] - stat['finite']} nem véges érték.",
                )
                expected_unit = EXPECTED_UNITS[name]
                result.check(
                    variable.attrs.get("units") == expected_unit,
                    f"{name}: a mértékegység helyes ({expected_unit}).",
                    f"{name}: hibás mértékegység {variable.attrs.get('units')!r}.",
                )
                pole = values[:, :, [0, -1], :]
                pole_std = np.nanstd(pole, axis=-1)
                scale = max(float(np.nanstd(values)), 1.0)
                result.check(
                    float(np.nanmax(pole_std)) <= 1e-7 * scale,
                    f"{name}: a pólusok longitudinálisan konzisztensek.",
                    f"{name}: a póluson longitudinális szórás maradt "
                    f"({float(np.nanmax(pole_std)):.6g}).",
                )

            time_units = str(dataset.time.attrs.get("units", ""))
            result.check(
                bool(time_units),
                "Az időkoordinátának van units attribútuma.",
                "Az időkoordinátáról hiányzik a units attribútum.",
            )
            if "since" in time_units:
                result.check(
                    "calendar" in dataset.time.attrs,
                    "A relatív időkoordinátának van calendar attribútuma.",
                    "A relatív időkoordinátáról hiányzik a calendar attribútum.",
                )
            if source_dir:
                compare_source(dataset, source_dir, result)
    except Exception as exc:
        result.errors.append(f"xarray megnyitási/ellenőrzési hiba: {exc}")
        return result

    if shutil.which("ncdump"):
        ok, output = command_ok(["ncdump", "-h", str(path)])
        result.check(
            ok,
            "A fájl ncdump-pal megnyitható.",
            f"Az ncdump nem tudta megnyitni: {output[-500:]}",
        )
    else:
        result.warnings.append("Az ncdump nem érhető el; ezt a próbát kihagytam.")
    return result


def validate_time_collection(results: list[FileResult]) -> list[str]:
    messages: list[str] = []
    pairs = [
        (time, result.path.name)
        for result in results
        for time in result.time_values
    ]
    if not pairs:
        return ["Nem volt ellenőrizhető időpont."]
    times = np.array([item[0] for item in pairs], dtype=float)
    if len(np.unique(times)) != len(times):
        messages.append("HIBA: duplikált időpont van a fájlkészletben.")
    if np.any(np.diff(times) <= 0):
        messages.append("HIBA: a fájlsorrendben az idő nem szigorúan növekvő.")
    if len(times) >= 3:
        diffs = np.diff(times)
        cadence = float(np.median(diffs))
        gaps = int(np.count_nonzero(~np.isclose(diffs, cadence, rtol=1e-9, atol=1e-6)))
        messages.append(
            f"Medián időlépés: {cadence:g} s; ettől eltérő közök száma: {gaps}."
        )
    else:
        messages.append(
            "Egy-két időpont áll rendelkezésre; duplikáció vizsgálható, teljes "
            "folytonosság még nem."
        )
    return messages


def validate_grib(grib_dir: Path | None) -> list[str]:
    if grib_dir is None:
        return ["A GRIB2-validációhoz nem adtak meg --grib-dir könyvtárat."]
    files = sorted(grib_dir.glob("*.grib2"))
    if not files:
        return ["Nem található GRIB2-fájl."]
    if not shutil.which("cdo"):
        return ["A CDO nem érhető el, ezért a GRIB2 szerkezete nem ellenőrizhető."]
    messages: list[str] = []
    for path in files:
        ok, output = command_ok(["cdo", "-s", "sinfo", str(path)])
        messages.append(
            f"{'OK' if ok else 'HIBA'} `{path.name}`: "
            f"{'CDO-val olvasható.' if ok else output[-500:]}"
        )
    return messages


def markdown_table(rows: Iterable[Iterable[Any]]) -> str:
    rows = [list(map(str, row)) for row in rows]
    if not rows:
        return ""
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = [
        "| " + " | ".join(value.ljust(widths[i]) for i, value in enumerate(row)) + " |"
        for row in rows
    ]
    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    return "\n".join((lines[0], separator, *lines[1:]))


def write_report(
    path: Path,
    results: list[FileResult],
    time_messages: list[str],
    grib_messages: list[str],
) -> None:
    errors = sum(len(item.errors) for item in results)
    warnings = sum(len(item.warnings) for item in results)
    lines = [
        "# RePLaT bemenetek validációs jelentése",
        "",
        f"- Vizsgált NetCDF-fájlok: **{len(results)}**",
        f"- Hibák: **{errors}**",
        f"- Figyelmeztetések: **{warnings}**",
        f"- Összesített állapot: **{'SIKERES' if errors == 0 else 'HIBÁS'}**",
        "",
        "## Időkoordináta a fájlkészletben",
        "",
        *[f"- {message}" for message in time_messages],
        "",
    ]
    for result in results:
        lines.extend(
            [
                f"## `{result.path.name}`",
                "",
                f"Állapot: **{'SIKERES' if not result.errors else 'HIBÁS'}**",
                "",
                "### Ellenőrzések",
                "",
                *[f"- OK: {message}" for message in result.passes],
                *[f"- HIBA: {message}" for message in result.errors],
                *[f"- FIGYELMEZTETÉS: {message}" for message in result.warnings],
                "",
                "### Kimeneti statisztikák",
                "",
            ]
        )
        rows: list[list[Any]] = [
            ["változó", "minimum", "maximum", "átlag", "szórás", "területsúlyozott átlag"]
        ]
        for name, stat in result.stats.items():
            rows.append(
                [
                    name,
                    f"{stat['min']:.8g}",
                    f"{stat['max']:.8g}",
                    f"{stat['mean']:.8g}",
                    f"{stat['std']:.8g}",
                    f"{stat['area_weighted_mean']:.8g}",
                ]
            )
        lines.extend([markdown_table(rows), ""])
        if result.source_comparison:
            lines.extend(["### Forrás–kimenet összehasonlítás", ""])
            rows = [
                [
                    "változó",
                    "forrás területi átlag",
                    "kimenet területi átlag",
                    "|Δátlag| / forrásszórás",
                    "forrás min..max",
                    "kimenet min..max",
                ]
            ]
            for name, values in result.source_comparison.items():
                rows.append(
                    [
                        name,
                        f"{values['source_area_mean']:.8g}",
                        f"{values['output_area_mean']:.8g}",
                        f"{values['normalized_mean_difference']:.5g}",
                        f"{values['source_min']:.6g} .. {values['source_max']:.6g}",
                        f"{values['output_min']:.6g} .. {values['output_max']:.6g}",
                    ]
                )
            lines.extend(
                [
                    markdown_table(rows),
                    "",
                    "Megjegyzés: a forrás magassági, a kimenet nyomási szinteken van. "
                    "Ezért ez tartomány- és nagyságrendi konzisztenciavizsgálat, nem "
                    "pontonkénti azonosságteszt.",
                    "",
                ]
            )
    lines.extend(
        [
            "## GRIB2",
            "",
            *[f"- {message}" for message in grib_messages],
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    files = sorted(args.input_dir.expanduser().resolve().glob("*.nc"))
    if not files:
        print(f"ERROR: no .nc files in {args.input_dir}", file=sys.stderr)
        return 2
    source_dir = args.source_dir.expanduser().resolve() if args.source_dir else None
    results = [validate_netcdf(path, source_dir) for path in files]
    time_messages = validate_time_collection(results)
    grib_messages = validate_grib(
        args.grib_dir.expanduser().resolve() if args.grib_dir else None
    )
    write_report(args.report.expanduser().resolve(), results, time_messages, grib_messages)
    errors = sum(len(item.errors) for item in results)
    warnings = sum(len(item.warnings) for item in results)
    print(
        f"Validated {len(results)} NetCDF file(s): {errors} error(s), "
        f"{warnings} warning(s). Report: {args.report}"
    )
    return 1 if errors or (args.strict_warnings and warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
