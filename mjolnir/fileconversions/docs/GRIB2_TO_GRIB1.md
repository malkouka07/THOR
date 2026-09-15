# GRIB2 → GRIB1

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

`scripts/grib2_to_grib1.py` decodes ecCodes messages, records their metadata,
and groups them into complete `(valid time, field)` pressure stacks. It requires
one common source level set, unique messages and an identical regular grid.
Then it derives exact integer-hPa targets, interpolates values linearly in
`log(p)`, creates fresh GRIB1 messages and reopens the output. Original GRIB2
validity datetimes are copied exactly.

Only `isobaricInPa` and `isobaricInhPa` surfaces enter pressure stacks. Surface,
height-above-ground and other level types are rejected or explicitly reported
as skipped; a 10 m wind can therefore never become a 10 hPa wind. GRIB bitmaps
are decoded as missing masks and missing brackets remain missing during vertical
interpolation.

It never toggles an edition key. GRIB2 0/2/9 geometric W is unsupported rather than relabeled as GRIB1 pressure omega. Default `--on-unsupported error`; explicit skip is reported. GRIB2 fixed-surface scaled values are used to preserve exact Pa metadata even when ecCodes' convenience `level` is displayed in hPa.

GRIB1 level policies and output layouts match the HDF5 converter. The production
default is `--pressure-level-policy hpa-aligned --level-encoding strict`.
Zero-based logical time selection is supported. The historical Venus GRIB2
sample contains geometric `wz` (`0/2/9`, m/s), so it can produce U/V only; the
three-variable benchmark first creates GRIB2 from HDF5 with explicit omega.
See [VENUS5_GRIB1.md](VENUS5_GRIB1.md).
