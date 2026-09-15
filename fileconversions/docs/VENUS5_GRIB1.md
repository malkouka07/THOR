# Venus5 GRIB1 production profile

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

## Ready-to-use files

The generated products are outside the repository in:

```text
/home/malkouka/THOR_POE_HOST/venus_5_fileconversions/
├── direct_hdf5_to_grib1_hpa/   # preferred production path
├── hdf5_to_grib2_source/       # 20-level benchmark input
├── grib2_to_grib1_hpa/         # GRIB2 adapter benchmark
├── netcdf_adapter_example/     # older Venus NetCDF, U/V only
└── direct_vs_grib2_adapter.csv
```

The two Venus5 GRIB1 directories each contain U, V and omega, with 11 native
model times and 17 pressure levels: `3 × 11 × 17 = 561` messages.

## Pressure rule

GRIB1 `isobaricInhPa` stores a positive integer hPa coordinate. The converter
does not merely round a label. It derives source-following hPa surfaces inside
the common source range, removes duplicate surfaces, and evaluates every field
there by piecewise-linear interpolation in `log(p)`. Extrapolation is forbidden.

For this Venus5 pressure grid the deterministic target is:

```text
hPa: 995 987 975 950 904 824 698 534 362 220 126 70 37 18 8 3 1
Pa:  99500 98700 97500 95000 90400 82400 69800 53400 36200
     22000 12600 7000 3700 1800 800 300 100
```

`996 hPa` would exceed the deepest source surface (`99578.66 Pa`), so the
first level is `995 hPa`. Four source levels are below `1 hPa`; GRIB1 can emit
only the `1 hPa` surface, so three duplicate upper-atmosphere targets are
explicitly marked omitted in `reports/pressure_level_mapping.csv`.

Use `--pressure-level-policy hpa-aligned --level-encoding strict`. The older
`hpa-rounded` writer mode changes coordinates without recomputing values and is
not the production policy.

## Variable and time profile

| Field | GRIB1 wire ID | ecCodes `paramId` | Unit |
|---|---:|---:|---|
| U | `33.2` | 131 | `m s-1` |
| V | `34.2` | 132 | `m s-1` |
| omega | `39.2` | 135 | `Pa s-1` |

The colleague's `135.128` is the ECMWF local-table representation of pressure
omega. The portable WMO table-2 representation used here is `39.2`; ecCodes
maps both to canonical parameter 135 with `Pa s-1`. They are semantically the
same physical quantity but not byte-identical parameter metadata.

The source has elapsed times `0, 86400, …, 864000 s`. No temporal interpolation
is performed. GRIB maps those unchanged offsets onto the configurable technical
epoch, giving `2000-01-01 … 2000-01-11` with the default epoch. These are model
coordinates, not claimed Earth observation dates.

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
.venv-fileconversions/bin/python fileconversions/scripts/hdf5_to_grib1.py \
  --input-dir /home/malkouka/THOR_POE_HOST/venus_5_long_benchmark \
  --processed-hdf5-pattern 'regrid_venus_*.h5' \
  --output-dir /home/malkouka/THOR_POE_HOST/venus_5_fileconversions/direct_hdf5_to_grib1_hpa \
  --variables u v omega --vertical-velocity-mode hydrostatic \
  --pressure-level-policy hpa-aligned --level-encoding strict \
  --lat-step 4 --lon-step 4 --file-layout per-variable --bits-per-value 24 \
  --overwrite

.venv-fileconversions/bin/python fileconversions/scripts/hdf5_to_grib2.py \
  --input-dir /home/malkouka/THOR_POE_HOST/venus_5_long_benchmark \
  --processed-hdf5-pattern 'regrid_venus_*.h5' \
  --output-dir /home/malkouka/THOR_POE_HOST/venus_5_fileconversions/hdf5_to_grib2_source \
  --variables u v omega --vertical-velocity-mode hydrostatic \
  --pressure-level-policy source --lat-step 4 --lon-step 4 \
  --file-layout per-variable --bits-per-value 24 --overwrite

.venv-fileconversions/bin/python fileconversions/scripts/grib2_to_grib1.py \
  --input-dir /home/malkouka/THOR_POE_HOST/venus_5_fileconversions/hdf5_to_grib2_source \
  --input-glob '*.grib2' \
  --output-dir /home/malkouka/THOR_POE_HOST/venus_5_fileconversions/grib2_to_grib1_hpa \
  --pressure-level-policy hpa-aligned --level-encoding strict \
  --file-layout per-variable --bits-per-value 24 --overwrite
```

The 4° grid and 24-bit request are this benchmark's choices, not format
requirements. Constant initial fields are legally stored by ecCodes with zero
data bits; later non-constant fields use 24 bits.

## Validation result

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
