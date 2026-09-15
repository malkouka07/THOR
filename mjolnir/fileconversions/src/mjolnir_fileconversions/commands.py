"""Command implementations shared by the small user-facing scripts."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, Sequence

from .discovery import (
    HDF5_SUFFIXES,
    classify_collection,
    discover_paths,
    write_classification_csv,
)
from .errors import ConversionError, PressureEncodingError
from .readers.grib2_reader import read_grib2_collection
from .readers.hdf5_reader import read_processed_hdf5_collection
from .readers.netcdf_reader import read_netcdf_collection
from .validation.grib_validation import roundtrip_against_canonical, validate_grib_files
from .validation.parity import compare_grib_collections
from .validation.reporting import (
    write_csv,
    write_markdown_report,
    write_pressure_mapping,
    write_processing_stages,
)
from .writers.grib1_writer import write_grib1_dataset
from .writers.grib_common import EncodedLevel, encode_grib1_level
from .writers.grib2_writer_adapter import write_grib2_dataset
from .writers.netcdf_diagnostic_writer import write_netcdf_diagnostic


_HDF5_INDEX_RE = re.compile(r"_(?P<index>[0-9]+)\.h5$")


def _requested_time_indices(args) -> list[int] | None:
    if getattr(args, "time_index", None) is not None and getattr(args, "time_indices", None) is not None:
        raise ConversionError("use only one of --time-index and --time-indices")
    if getattr(args, "time_index", None) is not None:
        values = [int(args.time_index)]
    elif getattr(args, "time_indices", None) is not None:
        values = [int(value) for value in args.time_indices]
    else:
        return None
    if not values:
        raise ConversionError("--time-indices cannot be empty")
    if any(value < 0 for value in values):
        raise ConversionError("time indices must be non-negative")
    if len(set(values)) != len(values):
        raise ConversionError("duplicate time indices")
    return values


def _hdf5_index(path: Path) -> int:
    match = _HDF5_INDEX_RE.search(path.name)
    return int(match.group("index")) if match else 2**63 - 1


def configure_logging(level: str = "INFO", log_file: Path | None = None) -> logging.Logger:
    logger = logging.getLogger("mjolnir_fileconversions")
    logger.handlers.clear()
    logger.setLevel(getattr(logging, level.upper()))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def _hdf5_candidates(args, report_dir: Path) -> list[Path]:
    if args.input:
        candidates = [Path(item).expanduser().resolve() for item in args.input]
    elif args.input_glob:
        candidates = discover_paths(None, None, args.input_glob, HDF5_SUFFIXES)
    elif args.input_dir:
        root = Path(args.input_dir).expanduser().resolve()
        pattern = args.processed_hdf5_pattern or "*.h5"
        candidates = sorted(root.rglob(pattern))
    else:
        raise ConversionError("one of --input, --input-dir or --input-glob is required")
    all_hdf5 = candidates
    if args.input_dir and not args.processed_hdf5_pattern:
        all_hdf5 = sorted(Path(args.input_dir).expanduser().resolve().rglob("*.h5"))
    classifications = classify_collection(all_hdf5)
    selected_paths = {path.resolve() for path in candidates}
    processed = [
        Path(item.file_path)
        for item in classifications
        if Path(item.file_path) in selected_paths
        and item.classification == "mjolnir_processed"
    ]
    if not processed:
        rows = [
            type(item)(**{**item.as_dict(), "selected_for_conversion": False})
            for item in classifications
        ]
        write_classification_csv(report_dir / "hdf5_input_classification.csv", rows)
        summary = "\n".join(
            f"- {item.file_name}: {item.classification} ({item.reason})" for item in rows
        )
        raise ConversionError(
            "No Mjolnir-processed HDF5 was found; refusing native fallback.\n" + summary
        )
    # Prefer Mjolnir pressure-grid products when automatic discovery sees both
    # pressure- and height-grid products for the same time range.
    processed.sort(
        key=lambda path: (
            0
            if path.name.startswith("regrid_")
            and not path.name.startswith("regrid_height_")
            else 1,
            _hdf5_index(path),
            str(path),
        )
    )
    if args.input_dir and not args.processed_hdf5_pattern:
        pressure_grid = [
            path
            for path in processed
            if path.name.startswith("regrid_")
            and not path.name.startswith("regrid_height_")
        ]
        if pressure_grid:
            processed = pressure_grid
    requested_indices = _requested_time_indices(args)
    if requested_indices is not None:
        requested_set = set(requested_indices)
        processed = [path for path in processed if _hdf5_index(path) in requested_set]
        found = {_hdf5_index(path) for path in processed}
        if found != requested_set:
            rows = [
                type(item)(
                    **{
                        **item.as_dict(),
                        "selected_for_conversion": Path(item.file_path) in set(processed),
                    }
                )
                for item in classifications
            ]
            write_classification_csv(report_dir / "hdf5_input_classification.csv", rows)
            raise ConversionError(
                f"requested HDF5 source indices were not all found: missing {sorted(requested_set - found)}"
            )
    if args.test_mode and args.max_files is None:
        processed = processed[:3]
    elif args.max_files is not None:
        if args.max_files <= 0:
            raise ConversionError("--max-files must be positive")
        processed = processed[: args.max_files]
    final_paths = set(processed)
    rows = [
        type(item)(
            **{
                **item.as_dict(),
                "selected_for_conversion": Path(item.file_path) in final_paths,
            }
        )
        for item in classifications
    ]
    write_classification_csv(report_dir / "hdf5_input_classification.csv", rows)
    return processed


def _write_variable_mapping(report_dir: Path, dataset) -> None:
    rows = []
    for name in dataset.fields:
        rows.append(
            {
                "canonical_variable": name,
                "units": dataset.units[name],
                "grib1_table_version": 2,
                "grib1_wire_parameter": {"eastward_wind": 33, "northward_wind": 34, "omega": 39}[name],
                "eccodes_param_id": {"eastward_wind": 131, "northward_wind": 132, "omega": 135}[name],
                "grib2_parameter": {"eastward_wind": "0/2/2", "northward_wind": "0/2/3", "omega": "0/2/8"}[name],
                "packing": "grid_simple; bitsPerValue set by --bits-per-value",
                "omega_method": dataset.metadata.get("omega_method", "not applicable"),
                "status": "mapped",
            }
        )
    write_csv(report_dir / "variable_mapping.csv", rows)


def _preflight_grib1_levels(args, levels: Iterable[float]) -> tuple[list[EncodedLevel], dict[int, str]]:
    encoded: list[EncodedLevel] = []
    errors: dict[int, str] = {}
    for level in levels:
        try:
            encoded.append(
                encode_grib1_level(
                    float(level),
                    args.level_encoding,
                    max_absolute_error_pa=args.max_level_absolute_error_pa,
                    max_relative_error=args.max_level_relative_error,
                )
            )
        except PressureEncodingError as exc:
            errors[int(round(float(level)))] = str(exc)
    return encoded, errors


def _raise_first_level_error(levels: Iterable[float], errors: dict[int, str]) -> None:
    for level in levels:
        message = errors.get(int(round(float(level))))
        if message:
            raise PressureEncodingError(message)


def _post_validate(
    output_paths: Sequence[Path],
    output_dir: Path,
    edition: int,
    *,
    dataset=None,
    technical_epoch: str = "2000-01-01T00:00:00Z",
) -> None:
    rows, warnings = validate_grib_files(output_paths, expected_edition=edition)
    report_dir = output_dir / "reports"
    write_csv(report_dir / "test_manifest.csv", rows)
    if dataset is None:
        roundtrip_rows = rows
        warnings.append(
            "canonical writer input was not retained for this adapter; structural decode validation only"
        )
    else:
        roundtrip_rows = roundtrip_against_canonical(
            output_paths,
            dataset,
            technical_epoch=technical_epoch,
            conversion_mode=f"canonical-to-GRIB{edition}",
        )
    write_csv(report_dir / "roundtrip_statistics.csv", roundtrip_rows)
    status = (
        "passed"
        if all(row["status"] == "passed" for row in [*rows, *roundtrip_rows])
        else "failed"
    )
    write_markdown_report(
        report_dir / "validation_report.md",
        "GRIB validation report",
        [
            f"- Edition: {edition}",
            f"- Messages: {len(rows)}",
            f"- Status: **{status}**",
            *[f"- Warning: {warning}" for warning in warnings],
        ],
    )


def convert_hdf5(args, *, edition: int) -> list[Path]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    report_dir = output_dir / "reports"
    logger = configure_logging(args.log_level, Path(args.log_file) if args.log_file else output_dir / "logs" / f"hdf5_to_grib{edition}.log")
    if args.input_kind != "mjolnir-processed":
        raise ConversionError("Only --input-kind mjolnir-processed is implemented")
    paths = _hdf5_candidates(args, report_dir)
    logger.info("Selected %d verified Mjolnir-processed HDF5 file(s)", len(paths))
    dataset, pressure_mapping = read_processed_hdf5_collection(
        paths,
        variables=args.variables,
        lat_step=args.lat_step,
        lon_step=args.lon_step,
        vertical_velocity_mode=args.vertical_velocity_mode,
        pressure_level_policy=args.pressure_level_policy,
        planet_file=args.planet_file,
        grid_file=args.grid_file,
    )
    write_processing_stages(report_dir / "processing_stage_detection.csv", dataset.stages)
    write_pressure_mapping(report_dir / "pressure_level_mapping.csv", pressure_mapping)
    _write_variable_mapping(report_dir, dataset)
    if args.keep_intermediate:
        write_netcdf_diagnostic(dataset, output_dir / "canonical_intermediate.nc", overwrite=args.overwrite)
    if edition == 1:
        preflight, encoding_errors = _preflight_grib1_levels(args, dataset.level_pa)
        write_pressure_mapping(
            report_dir / "pressure_level_mapping.csv",
            pressure_mapping,
            preflight,
            encoding_errors,
            args.level_encoding,
        )
        _raise_first_level_error(dataset.level_pa, encoding_errors)
        outputs, encoded = write_grib1_dataset(
            dataset,
            output_dir,
            file_layout=args.file_layout,
            level_encoding=args.level_encoding,
            overwrite=args.overwrite,
            max_absolute_error_pa=args.max_level_absolute_error_pa,
            max_relative_error=args.max_level_relative_error,
            bits_per_value=args.bits_per_value,
            technical_epoch=args.technical_epoch,
        )
        write_pressure_mapping(report_dir / "pressure_level_mapping.csv", pressure_mapping, encoded)
    else:
        outputs = write_grib2_dataset(
            dataset,
            output_dir,
            file_layout=args.file_layout,
            overwrite=args.overwrite,
            bits_per_value=args.bits_per_value,
            technical_epoch=args.technical_epoch,
        )
    _post_validate(
        outputs,
        output_dir,
        edition,
        dataset=dataset,
        technical_epoch=args.technical_epoch,
    )
    logger.info("Created %d GRIB%d output file(s)", len(outputs), edition)
    return outputs


def convert_netcdf(args) -> list[Path]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    report_dir = output_dir / "reports"
    logger = configure_logging(args.log_level, Path(args.log_file) if args.log_file else output_dir / "logs" / "netcdf_to_grib1.log")
    paths = discover_paths(
        [Path(item) for item in args.input] if args.input else None,
        Path(args.input_dir) if args.input_dir else None,
        args.input_glob or "*.nc",
        {".nc", ".nc4"},
    )
    if args.max_files is not None:
        if args.max_files <= 0:
            raise ConversionError("--max-files must be positive")
        paths = paths[: args.max_files]
    elif args.test_mode:
        paths = paths[:3]
    dataset, pressure_mapping = read_netcdf_collection(
        paths,
        variables=args.variables,
        lat_step=args.lat_step,
        lon_step=args.lon_step,
        regrid=args.regrid,
        vertical_velocity_mode=args.vertical_velocity_mode,
        gravity_m_s2=args.gravity,
        time_indices=_requested_time_indices(args),
        pressure_level_policy=args.pressure_level_policy,
    )
    write_processing_stages(report_dir / "processing_stage_detection.csv", dataset.stages)
    write_pressure_mapping(report_dir / "pressure_level_mapping.csv", pressure_mapping)
    _write_variable_mapping(report_dir, dataset)
    if args.keep_intermediate:
        write_netcdf_diagnostic(
            dataset,
            output_dir / "canonical_intermediate.nc",
            overwrite=args.overwrite,
        )
    preflight, encoding_errors = _preflight_grib1_levels(args, dataset.level_pa)
    write_pressure_mapping(
        report_dir / "pressure_level_mapping.csv",
        pressure_mapping,
        preflight,
        encoding_errors,
        args.level_encoding,
    )
    _raise_first_level_error(dataset.level_pa, encoding_errors)
    outputs, encoded = write_grib1_dataset(
        dataset,
        output_dir,
        file_layout=args.file_layout,
        level_encoding=args.level_encoding,
        overwrite=args.overwrite,
        max_absolute_error_pa=args.max_level_absolute_error_pa,
        max_relative_error=args.max_level_relative_error,
        bits_per_value=args.bits_per_value,
        technical_epoch=args.technical_epoch,
    )
    write_pressure_mapping(report_dir / "pressure_level_mapping.csv", pressure_mapping, encoded)
    _post_validate(
        outputs,
        output_dir,
        1,
        dataset=dataset,
        technical_epoch=args.technical_epoch,
    )
    logger.info("Created %d GRIB1 output file(s)", len(outputs))
    return outputs


def convert_grib2(args) -> list[Path]:
    """Convert complete GRIB2 pressure stacks with real vertical interpolation."""
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir = output_dir / "reports"
    logger = configure_logging(args.log_level, Path(args.log_file) if args.log_file else output_dir / "logs" / "grib2_to_grib1.log")
    paths = discover_paths(
        [Path(item) for item in args.input] if args.input else None,
        Path(args.input_dir) if args.input_dir else None,
        args.input_glob or "*.grib2",
        {".grib2", ".grb2", ".grib", ".grb"},
    )
    if args.max_files is not None:
        if args.max_files <= 0:
            raise ConversionError("--max-files must be positive")
        paths = paths[: args.max_files]
    elif args.test_mode:
        paths = paths[:3]
    requested_time_indices = _requested_time_indices(args)
    dataset, pressure_mapping, messages = read_grib2_collection(
        paths,
        on_unsupported=args.on_unsupported,
        time_indices=requested_time_indices,
        pressure_level_policy=args.pressure_level_policy,
    )
    selected_valid_times = set(dataset.metadata["absolute_valid_times_utc"])
    target_levels = " ".join(str(int(level)) for level in dataset.level_pa)
    vertical_interpolation_performed = any(
        item.interpolation_performed for item in pressure_mapping
    )
    parameter_ids = {"eastward_wind": 131, "northward_wind": 132, "omega": 135}
    wire_parameters = {"eastward_wind": 33, "northward_wind": 34, "omega": 39}
    mapping_rows: list[dict[str, object]] = []
    for message in messages:
        meta = message.metadata
        valid_text = message.valid_datetime.isoformat().replace("+00:00", "Z")
        unsupported = not message.field_name
        filtered = not unsupported and valid_text not in selected_valid_times
        mapping_rows.append(
            {
                "source_file": str(message.source_file),
                "message_index": message.message_index,
                "source_valid_time": valid_text,
                "source_discipline": meta.get("discipline"),
                "source_category": meta.get("parameterCategory"),
                "source_parameter_number": meta.get("parameterNumber"),
                "source_short_name": meta.get("shortName"),
                "source_name": meta.get("name"),
                "source_units": meta.get("units"),
                "source_type_of_level": meta.get("typeOfLevel"),
                "source_level_pa": message.pressure_level_pa,
                "target_table_version": 2,
                "target_wire_parameter": wire_parameters.get(message.field_name, ""),
                "target_eccodes_param_id": parameter_ids.get(message.field_name, ""),
                "target_units": (
                    "Pa s-1" if message.field_name == "omega" else "m s-1"
                ),
                "target_type_of_level": (
                    "isobaricInPa"
                    if args.level_encoding == "ecmwf-pa"
                    else "isobaricInhPa"
                ),
                "target_levels_pa": target_levels if not unsupported else "",
                "mapping_status": (
                    "skipped unsupported"
                    if unsupported
                    else "filtered by time selection"
                    if filtered
                    else (
                        "stack interpolated and mapped"
                        if vertical_interpolation_performed
                        else "stack mapped without vertical interpolation"
                    )
                ),
                "information_loss": (
                    "unsupported GRIB2 parameter skipped"
                    if unsupported
                    else "GRIB2-only metadata is not encoded in GRIB1"
                ),
                "notes": (
                    (
                        "Each target value is evaluated by linear interpolation in log(p); "
                        "this is not a source-message-to-target-message relabeling."
                        if vertical_interpolation_performed
                        else "Source and target pressure levels are identical; values are copied."
                    )
                    if not unsupported and not filtered
                    else ""
                ),
            }
        )
    write_csv(report_dir / "grib2_to_grib1_mapping.csv", mapping_rows)
    write_processing_stages(report_dir / "processing_stage_detection.csv", dataset.stages)
    write_pressure_mapping(report_dir / "pressure_level_mapping.csv", pressure_mapping)
    _write_variable_mapping(report_dir, dataset)

    preflight, encoding_errors = _preflight_grib1_levels(args, dataset.level_pa)
    write_pressure_mapping(
        report_dir / "pressure_level_mapping.csv",
        pressure_mapping,
        preflight,
        encoding_errors,
        args.level_encoding,
    )
    _raise_first_level_error(dataset.level_pa, encoding_errors)
    result, encoded = write_grib1_dataset(
        dataset,
        output_dir,
        file_layout=args.file_layout,
        level_encoding=args.level_encoding,
        overwrite=args.overwrite,
        max_absolute_error_pa=args.max_level_absolute_error_pa,
        max_relative_error=args.max_level_relative_error,
        bits_per_value=args.bits_per_value,
        technical_epoch=args.technical_epoch,
    )
    write_pressure_mapping(
        report_dir / "pressure_level_mapping.csv", pressure_mapping, encoded
    )
    _post_validate(
        result,
        output_dir,
        1,
        dataset=dataset,
        technical_epoch=args.technical_epoch,
    )
    logger.info("Converted %d GRIB2 file(s) into %d GRIB1 file(s)", len(paths), len(result))
    return result


def validate_command(args) -> list[dict[str, object]]:
    paths = discover_paths(
        [Path(item) for item in args.input] if args.input else None,
        Path(args.input_dir) if args.input_dir else None,
        args.input_glob or "*",
        {".grib1", ".grb1", ".grib2", ".grb2", ".grib", ".grb"},
    )
    rows, warnings = validate_grib_files(paths, expected_edition=args.edition)
    report = Path(args.report).expanduser().resolve()
    write_csv(report.with_suffix(".csv"), rows)
    write_markdown_report(
        report,
        "GRIB validation report",
        [
            f"- Files: {len(paths)}",
            f"- Messages: {len(rows)}",
            f"- Failed messages: {sum(row['status'] != 'passed' for row in rows)}",
            *[f"- Warning: {item}" for item in warnings],
        ],
    )
    return rows


def compare_command(args) -> list[dict[str, object]]:
    grib1 = sorted(Path(args.grib1_dir).expanduser().resolve().glob(args.grib1_glob))
    grib2 = sorted(Path(args.grib2_dir).expanduser().resolve().glob(args.grib2_glob))
    rows = compare_grib_collections(grib1, grib2, packing_tolerance=args.packing_tolerance)
    write_csv(Path(args.report).expanduser().resolve(), rows)
    return rows
