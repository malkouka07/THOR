import argparse
from pathlib import Path

import pytest

from mjolnir_fileconversions.cli import parse_args_with_config
from mjolnir_fileconversions.errors import ConversionError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lat-step", type=float, default=4.0)
    parser.add_argument("--level-encoding", choices=("strict", "hpa-rounded"), default="strict")
    return parser


def test_yaml_defaults_and_cli_precedence(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text(
        "output_dir: products\n"
        "target_grid:\n"
        "  latitude_step_degrees: 6\n"
        "level_encoding: strict\n",
        encoding="utf-8",
    )
    args = parse_args_with_config(
        _parser(), ["--config", str(config), "--lat-step", "3"]
    )
    assert args.output_dir == tmp_path / "products"
    assert args.lat_step == 3


def test_yaml_rejects_unknown_keys(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text("mystery: true\n", encoding="utf-8")
    with pytest.raises(ConversionError, match="not supported"):
        parse_args_with_config(_parser(), ["--config", str(config), "--output-dir", "out"])
