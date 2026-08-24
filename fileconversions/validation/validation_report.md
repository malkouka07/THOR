# Consolidated validation report

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

- Unit tests: **passed**, 26 tests; one non-fatal system NumPy ABI warning recorded.
- Synthetic GRIB1 write/read: **passed**.
- Synthetic GRIB2 write/read: **passed**.
- Synthetic GRIB1–GRIB2 parity: **passed**, 9/9 messages, maximum absolute difference 0.
- Real Mjolnir-processed HDF5 → GRIB2: **passed**, 60/60 messages; ecCodes and CDO reopened all files.
- Real canonical → GRIB2 round-trip: **passed**, maximum absolute error `1.9073486328125e-06` against tolerance `1e-4`; missing-mask mismatches 0.
- Real Mjolnir-processed HDF5 → GRIB1 strict: **blocked by unsupported GRIB1 pressure level** at 99,578 Pa; no partial GRIB1.
- Real GRIB2 → GRIB1 strict: **blocked by unsupported GRIB1 pressure level** at 99,578 Pa; mapping records the rejected message.
- Real NetCDF → GRIB1 strict: **blocked by unsupported GRIB1 pressure level** at 97,895 Pa; no partial GRIB1.
- Real full-level GRIB1–GRIB2 parity: **not claimable**, because strict GRIB1 creation is correctly blocked.
- Upstream Mjolnir regeneration: **blocked by missing PyCUDA/CUDA dependency**; no replacement native interpolator was implemented.
- Optional validators unavailable: `grib_ls`, `grib_dump`, `wgrib`, `wgrib2`.

Scientific/code status remains unvalidated until manual review by Márkó.
