"""Explain stable entry points; dedicated scripts keep complete per-command help."""

from pathlib import Path


def main() -> int:
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    print("Available commands:")
    for name in ("hdf5_to_grib1.py", "hdf5_to_grib2.py", "grib2_to_grib1.py", "netcdf_to_grib1.py", "validate_grib.py", "compare_grib1_grib2.py"):
        print(f"  python {scripts / name} --help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
