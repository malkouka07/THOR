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
Pa/s, but their wire metadata is not byte-identical. Newly generated files write
each valid-time/variable pressure stack in strictly ascending pressure order,
top to bottom (`1, 3, 8, …, 995 hPa` for Venus5). Existing GRIB artifacts are
not modified by this code change and must be regenerated to acquire that order.
Centre and packing expectations still need consumer integration review.

The preserved Venus5 inputs contain daily states at elapsed times
`0, 86400, …, 864000 s`; conversion cannot recover genuine six-hour variability
from them. Six-hour products require actual Mjolnir snapshots at `21600 s`
intervals and matching native THOR time metadata. With a `300 s` THOR timestep,
that source cadence is produced with `n_out=72`. Temporal interpolation is not
performed because it would fabricate model states that were never written.

GRIB2 local tables, disciplines beyond the mapped winds/omega/temperature,
rich CF attributes, calendars and Venus metadata may be lost; mapping CSV and
sidecars document that loss. Temperature is absolute air temperature in K,
not potential temperature. GRIB1 minute-level time encoding cannot preserve
sub-minute model times and stops.

The standard GRIB1 regular-latitude/longitude template stores direction increments in 16-bit millidegrees, so configured steps above 65.535° are rejected explicitly. The default 4° grid is representable.
