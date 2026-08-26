# GRIB1 limitations

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

Standard GRIB1 isobaric levels use integer hPa. `strict` accepts only integer-Pa
levels divisible by 100. The production `hpa-aligned` policy first derives such
surfaces inside the source domain and genuinely interpolates every field there.
The Venus5 source has 20 levels but only 17 unique positive hPa targets; the
three duplicate sub-1-hPa targets are explicitly reported as omitted.

`hpa-rounded` is retained only for legacy diagnostics: it changes a pressure
label without recalculating the field and is not suitable for production.
`ecmwf-pa` is an ecCodes-specific GRIB1 representation with a 16-bit maximum of
65,535 Pa, so it cannot represent lower-atmosphere Venus levels near 100 kPa.

The colleague's example uses ECMWF local-table omega `135.128`; this converter
uses portable WMO table-2 omega `39.2`. ecCodes maps both to parameter 135 in
Pa/s, but their wire metadata is not byte-identical. Centre/message order and
packing expectations still need consumer integration review.

GRIB2 local tables, disciplines beyond the mapped winds/omega, rich CF attributes, calendars and Venus metadata may be lost; mapping CSV and sidecars document that loss. GRIB1 minute-level time encoding cannot preserve sub-minute model times and stops.

The standard GRIB1 regular-latitude/longitude template stores direction increments in 16-bit millidegrees, so configured steps above 65.535° are rejected explicitly. The default 4° grid is representable.
