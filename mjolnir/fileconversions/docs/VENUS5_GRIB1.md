# Venus5 GRIB1 production profile

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

## Ready-to-use files

The generated products are outside the repository in:

```text
/home/malkouka/THOR_conversion_data/outputs/venus_5_fileconversions/
├── direct_hdf5_to_grib1_hpa/   # preferred production path
├── hdf5_to_grib2_source/       # 20-level benchmark input
├── grib2_to_grib1_hpa/         # GRIB2 adapter benchmark
├── netcdf_adapter_example/     # older Venus NetCDF, U/V only
└── direct_vs_grib2_adapter.csv
```

These files are the preserved pre-change benchmark artifacts. They were not
regenerated as part of the pressure-order code change and therefore retain the
old descending-pressure message order. Regenerate them with the current writer
before using them to test the colleague's requested ordering.

The two preserved Venus5 GRIB1 directories each contain U, V and omega, with 11
native model times and 17 pressure levels: `3 × 11 × 17 = 561` messages. A new
four-variable production run would also contain temperature and therefore
would have `4 × 11 × 17 = 748` messages.

## Pressure rule

GRIB1 `isobaricInhPa` stores a positive integer hPa coordinate. The converter
does not merely round a label. It derives source-following hPa surfaces inside
the common source range, removes duplicate surfaces, and evaluates every field
there by piecewise-linear interpolation in `log(p)`. Extrapolation is forbidden.

For this Venus5 pressure grid the deterministic target set, in the order now
written to each valid-time/variable GRIB stack, is:

```text
hPa: 1 3 8 18 37 70 126 220 362 534 698 824 904 950 975 987 995
Pa:  100 300 800 1800 3700 7000 12600 22000 36200 53400 69800
     82400 90400 95000 97500 98700 99500
```

`996 hPa` would exceed the deepest source surface (`99578.66 Pa`), so the
deepest level is `995 hPa`. Four source levels are below `1 hPa`; GRIB1 can emit
only the `1 hPa` surface, so three duplicate upper-atmosphere targets are
explicitly marked omitted in `reports/pressure_level_mapping.csv`.

The canonical pressure array may still be stored in the source-derived opposite
direction. The writer reorders matching level indices and values together, so
changing message order does not attach a field to the wrong pressure surface.
Sidecars record both the canonical coordinate and the emitted message order.

Use `--pressure-level-policy hpa-aligned --level-encoding strict`. The older
`hpa-rounded` writer mode changes coordinates without recomputing values and is
not the production policy.

## Variable and time profile

| Field | GRIB1 wire ID | ecCodes `paramId` | Unit |
|---|---:|---:|---|
| U | `33.2` | 131 | `m s-1` |
| V | `34.2` | 132 | `m s-1` |
| omega | `39.2` | 135 | `Pa s-1` |
| temperature | `11.2` | 130 | `K` |

The colleague's `135.128` is the ECMWF local-table representation of pressure
omega. The portable WMO table-2 representation used here is `39.2`; ecCodes
maps both to canonical parameter 135 with `Pa s-1`. They are semantically the
same physical quantity but not byte-identical parameter metadata.

The source has elapsed times `0, 86400, …, 864000 s`. No temporal interpolation
is performed. GRIB maps those unchanged offsets onto the configurable technical
epoch, giving `2000-01-01 … 2000-01-11` with the default epoch. These are model
coordinates, not claimed Earth observation dates.

Consequently, this benchmark cannot truthfully produce six-hour meteorology.
For six-hour products, THOR must first write genuine states every `21600 s` and
Mjolnir must create a processed `regrid_*.h5` snapshot for every one of those
states, with its matching raw companion available for `simulation_time`. At the
current `300 s` THOR timestep this means `n_out=72`. Once those inputs exist,
the converter preserves their six-hour times directly; it does not interpolate
between the daily benchmark fields.

The processed HDF5 contains geometric `W` in `m s-1`, not omega. This production
run explicitly uses the documented approximation

```text
omega = -rho * g * W,  g = 8.87 m s-2
```

on the source grid before vertical interpolation. Legacy GRIB2/NetCDF `wz`
without density is skipped, never relabelled as omega.

## Reproduction

From the repository root, with `.venv-fileconversions` installed:

```bash
.venv-fileconversions/bin/python mjolnir/fileconversions/scripts/hdf5_to_grib1.py \
  --input-dir /home/malkouka/THOR_conversion_data/inputs/venus_5_long_benchmark \
  --processed-hdf5-pattern 'regrid_venus_*.h5' \
  --output-dir /home/malkouka/THOR_conversion_data/outputs/venus_5_fileconversions/direct_hdf5_to_grib1_grib1work \
  --variables u v omega temperature --vertical-velocity-mode hydrostatic \
  --pressure-level-policy hpa-aligned --level-encoding strict \
  --lat-step 4 --lon-step 4 --file-layout per-variable --bits-per-value 24 \
  --overwrite

.venv-fileconversions/bin/python mjolnir/fileconversions/scripts/hdf5_to_grib2.py \
  --input-dir /home/malkouka/THOR_conversion_data/inputs/venus_5_long_benchmark \
  --processed-hdf5-pattern 'regrid_venus_*.h5' \
  --output-dir /home/malkouka/THOR_conversion_data/outputs/venus_5_fileconversions/hdf5_to_grib2_grib1work \
  --variables u v omega temperature --vertical-velocity-mode hydrostatic \
  --pressure-level-policy source --lat-step 4 --lon-step 4 \
  --file-layout per-variable --bits-per-value 24 --overwrite

.venv-fileconversions/bin/python mjolnir/fileconversions/scripts/grib2_to_grib1.py \
  --input-dir /home/malkouka/THOR_conversion_data/outputs/venus_5_fileconversions/hdf5_to_grib2_grib1work \
  --input-glob '*.grib2' \
  --output-dir /home/malkouka/THOR_conversion_data/outputs/venus_5_fileconversions/grib2_to_grib1_grib1work \
  --pressure-level-policy hpa-aligned --level-encoding strict \
  --file-layout per-variable --bits-per-value 24 --overwrite
```

The 4° grid and 24-bit request are this benchmark's choices, not format
requirements. Constant initial fields are legally stored by ecCodes with zero
data bits; later non-constant fields use 24 bits.

These commands deliberately use new `*_grib1work` directories. They do not
overwrite the preserved three-variable pre-change benchmark named earlier.

## Preserved pre-change validation result

The following results describe the existing benchmark artifacts, not newly
regenerated ascending-order products:

- Direct HDF5→GRIB1: 3 files, 561 messages, all structural and canonical
  round-trip checks passed.
- HDF5→GRIB2: 3 files, 660 messages, 20 source levels and 11 times.
- GRIB2→GRIB1: 3 files, 561 messages, all checks passed; source GRIB2 validity
  datetimes are copied exactly.
- Direct versus adapter-derived GRIB1: all 561 comparisons passed at `0.002`;
  maximum absolute difference was `0.00162506104`. The difference includes the
  benchmark route's extra source-float→integer-Pa GRIB2 interpolation and both
  formats' packing.
- CDO reopens the products and reports 90×46 regular lon/lat, the 17 pressure
  levels above, daily times, and omega `39.2` in `Pa s**-1`.

Each product directory contains its own CSV reports and validation report.

A current one-time smoke conversion is stored outside Git under
`/home/malkouka/THOR_conversion_data/tests/grib1work_smoke/`. It contains U, V,
omega and temperature, with 68 decoded messages in the requested ascending
pressure order. Its reconstruction CSV compares 15 of the 20 original source
levels without extrapolation; this smoke result does not replace the preserved
11-time benchmark.
