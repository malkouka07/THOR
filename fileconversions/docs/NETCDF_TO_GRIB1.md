# NetCDF → GRIB1

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

The adapter supports CF-like NetCDF4/classic files and arbitrary source dimension order. Coordinate aliases include `lat/latitude/lats`, `lon/longitude/lons`, `level/lev/plev/pressure/pres`, and `time/Time/t`; `standard_name`, `axis`, units and one-dimensionality are also considered.

Pressure units Pa, hPa/mbar, kPa and bar are normalized to Pa. Time seconds/minutes/hours/days are normalized to elapsed seconds. Fields are transposed once to canonical order. `--regrid if-needed` skips a matching grid; `never` fails on mismatch and `always` explicitly remaps. Integer-Pa pressure coordinates are not shifted or reinterpolated.

U/V mapping uses names and CF standard names. Native `lagrangian_tendency_of_air_pressure` must have Pa/s units. `upward_air_velocity` is geometric m/s and requires explicit hydrostatic mode with density plus verified `--gravity`; it is never relabeled. NaN is encoded with a GRIB bitmap; Inf is rejected.

YAML defaults and zero-based per-file `--time-index/--time-indices` selection are supported. xarray opens inputs lazily and only selected time slices are materialized before canonical conversion. Multiple selected files are concatenated only after coordinate and variable parity checks.
