"""Shared command-line configuration helpers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import yaml

from .errors import ConversionError


_INFORMATIONAL_CONFIG_KEYS = {"review_status", "simulation_name"}


def _flatten_config(payload: object) -> dict[str, object]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ConversionError("the YAML configuration root must be a mapping")
    result = dict(payload)
    target_grid = result.pop("target_grid", {})
    if target_grid:
        if not isinstance(target_grid, dict):
            raise ConversionError("target_grid must be a YAML mapping")
        aliases = {
            "latitude_step_degrees": "lat_step",
            "longitude_step_degrees": "lon_step",
            "longitude_convention": "longitude_convention",
        }
        unknown = set(target_grid) - set(aliases)
        if unknown:
            raise ConversionError(f"unknown target_grid configuration keys: {sorted(unknown)}")
        result.update({aliases[key]: value for key, value in target_grid.items()})
    time = result.pop("time", {})
    if time:
        if not isinstance(time, dict):
            raise ConversionError("time must be a YAML mapping")
        aliases = {"technical_epoch": "technical_epoch"}
        unknown = set(time) - set(aliases)
        if unknown:
            raise ConversionError(f"unknown time configuration keys: {sorted(unknown)}")
        result.update({aliases[key]: value for key, value in time.items()})
    for key in _INFORMATIONAL_CONFIG_KEYS:
        result.pop(key, None)
    return result


def parse_args_with_config(
    parser: argparse.ArgumentParser, argv: Sequence[str] | None = None
) -> argparse.Namespace:
    """Load YAML defaults, then let explicit command-line arguments win."""
    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument("--config", type=Path)
    known, _ = preliminary.parse_known_args(argv)
    if known.config is None:
        return parser.parse_args(argv)

    config_path = known.config.expanduser().resolve()
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConversionError(f"cannot read YAML configuration {config_path}: {exc}") from exc
    defaults = _flatten_config(payload)
    actions = {action.dest: action for action in parser._actions}
    unknown = set(defaults) - set(actions)
    if unknown:
        raise ConversionError(f"configuration keys are not supported by this command: {sorted(unknown)}")
    for key, value in list(defaults.items()):
        action = actions[key]
        if action.type is Path and isinstance(value, str):
            candidate = Path(value).expanduser()
            defaults[key] = candidate if candidate.is_absolute() else config_path.parent / candidate
        elif action.type is Path and isinstance(value, list):
            defaults[key] = [
                item if Path(item).is_absolute() else config_path.parent / item for item in map(Path, value)
            ]
        if action.choices is not None:
            values = defaults[key] if isinstance(defaults[key], list) else [defaults[key]]
            invalid = [item for item in values if item not in action.choices]
            if invalid:
                raise ConversionError(
                    f"invalid configured value for {key}: {invalid}; choose from {list(action.choices)}"
                )
        if action.required:
            action.required = False
    parser.set_defaults(**defaults)
    return parser.parse_args(argv)
