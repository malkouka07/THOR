# Environment

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

Inspected on WSL2 Linux `5.15.167.4`, x86-64. The conversion environment is `.venv-fileconversions`, based on Ubuntu `/usr/bin/python3` 3.12.3 with system packages.

| Component | Version/status |
|---|---|
| NumPy | 1.26.4 |
| SciPy | 1.11.4 |
| xarray | Ubuntu package reports `999` |
| h5py | 3.10.0 |
| netCDF4 | 1.6.5 |
| h5netcdf | 1.3.0 |
| dask | 2023.12.1 |
| pandas | 2.1.4 |
| PyYAML | 6.0.1 |
| pytest | 7.4.4 |
| Python eccodes | 2.47.0; bundled ecCodes library 2.48.0 |
| cfgrib | 0.9.15.1 |
| CDO | 2.4.0, built with ecCodes 2.34.1 |
| h5dump | 1.10.10 |
| ncdump | available |

The implemented backend is Python ecCodes. CDO is an independent reopen check. `grib_ls`, `grib_dump`, `grib_set`, `grib_copy`, `codes_info`, `wgrib` and `wgrib2` are absent and reported as skipped optional validators. No `sudo` or system package mutation was used.

Reproduce with the installation commands in the main README and `requirements-fileconversions.txt`. The wheels `eccodeslib` and `eckitlib` supply the local ecCodes runtime.

The test run emits one non-fatal `numpy.ndarray size changed` warning from an Ubuntu binary extension loaded by the system-site-packages environment. All 26 tests pass, but a fully isolated wheel/conda environment is recommended before production to remove that ABI warning.
