# GRIB1 limitations

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

Standard GRIB1 isobaric levels use integer hPa. `strict` accepts only integer-Pa levels divisible by 100. Most inspected Venus levels are not, so full conversion stops without output and preserves a mapping report.

`hpa-rounded` is opt-in and checks both `--max-level-absolute-error-pa` and `--max-level-relative-error`. Very low pressures can have unacceptable relative error or round to 0 hPa. `ecmwf-pa` is an ecCodes-specific GRIB1 representation with a 16-bit maximum of 65,535 Pa, so it cannot represent lower-atmosphere Venus levels near 100 kPa. Neither compatibility mode is asserted RePLaT-compatible without an external reference.

No local historical GRIB1 reference file was found. Centre 98, WMO table version 2 and parameters 33/34/39 are verified against ecCodes definitions, but centre/message order/packing expectations of an external consumer still need manual integration review.

GRIB2 local tables, disciplines beyond the mapped winds/omega, rich CF attributes, calendars and Venus metadata may be lost; mapping CSV and sidecars document that loss. GRIB1 minute-level time encoding cannot preserve sub-minute model times and stops.

The standard GRIB1 regular-latitude/longitude template stores direction increments in 16-bit millidegrees, so configured steps above 65.535° are rejected explicitly. The default 4° grid is representable.
