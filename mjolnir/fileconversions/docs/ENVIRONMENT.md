# Environment

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

Inspected on WSL2 Linux, x86-64. The conversion environment is
`/home/malkouka/THOR/.venv-fileconversions`, based on Ubuntu
`/usr/bin/python3` 3.12.3 and isolated from system site packages.

| Component | Version/status |
|---|---|
| NumPy | 2.5.3 |
| SciPy | 1.18.1 |
| xarray | 2026.7.0 |
| h5py | 3.16.0 |
| netCDF4 | 1.7.4 |
| h5netcdf | 1.8.1 |
| dask | 2026.8.0 |
| pandas | 3.0.5 |
| PyYAML | 6.0.3 |
| pytest | 9.1.1 |
| Python eccodes | package 2.48.0; bundled ecCodes library 2.48.2 |
| cfgrib | 0.9.15.1 |
| CDO | 2.4.0, built with ecCodes 2.34.1 |
| h5dump | 1.10.10 |
| ncdump | available |

The implemented backend is Python ecCodes. CDO is an independent reopen check. `grib_ls`, `grib_dump`, `grib_set`, `grib_copy`, `codes_info`, `wgrib` and `wgrib2` are absent and reported as skipped optional validators. No `sudo` or system package mutation was used.

Reproduce with the installation commands in the main README and `mjolnir/fileconversions/requirements.txt`. The wheels `eccodeslib` and `eckitlib` supply the local ecCodes runtime.

All 36 tests pass and `pip check` reports no broken requirements. The test run
currently emits non-fatal warnings from the NetCDF stack: one binary-extension
size warning and xarray/NumPy 2.5 deprecation warnings. These do not change the
test result, but remain recorded for a future dependency-compatibility pass.
