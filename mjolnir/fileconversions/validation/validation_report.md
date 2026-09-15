# Consolidated validation report

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

- Unit tests: **passed**, 36 tests; one non-fatal system NumPy ABI warning recorded.
- Synthetic GRIB1 write/read: **passed**.
- Synthetic GRIB2 write/read: **passed**.
- Synthetic GRIB1–GRIB2 parity: **passed**, 9/9 messages, maximum absolute difference 0.
- Venus5 hPa target derivation: **passed**, 17 unique exact GRIB1 levels from 20 source levels; no extrapolation.
- Real Mjolnir-processed HDF5 → GRIB1: **passed**, 561/561 messages (U/V/omega, 11 times, 17 levels); ecCodes and CDO reopened all files.
- Real Mjolnir-processed HDF5 → GRIB2 benchmark: **passed**, 660/660 messages (3 fields, 11 times, 20 levels).
- Real GRIB2 → GRIB1 stack adapter: **passed**, 561/561 messages; original validity datetimes retained.
- Direct versus GRIB2-adapter GRIB1: **passed**, 561/561 comparisons at tolerance `0.002`; maximum absolute difference `0.00162506104`.
- Real NetCDF → GRIB1 adapter example: **passed**, 40/40 U/V messages on 20 exact hPa targets. Omega was omitted because the source has geometric W but no density.
- Upstream Mjolnir regeneration: **blocked by missing PyCUDA/CUDA dependency**; no replacement native interpolator was implemented.
- Optional validators unavailable: `grib_ls`, `grib_dump`, `wgrib`, `wgrib2`.

Scientific/code status remains unvalidated until manual review by Márkó.
