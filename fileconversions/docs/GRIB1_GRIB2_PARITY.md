# GRIB1–GRIB2 processing parity

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

| Processing step | Existing GRIB2 | New GRIB1 | Common implementation | Validated |
|---|---|---|---|---|
| Input identification | names/upstream knowledge | structural + metadata | readers/mapping | synthetic + real inspection |
| U/V vector rotation | already done by Mjolnir | never repeated | stage detection | source audit |
| Horizontal regridding | periodic bilinear | same | `processing/grid.py` | unit + real GRIB2 smoke |
| Poles | U/V zero, scalar ring mean | same | `horizontal_remap()` | unit |
| Pressure conversion | Pa | same | `processing/pressure.py` | unit + reports |
| Vertical interpolation | linear log(p) | same | `interpolate_log_pressure()` | unit |
| Omega Pa/s | historical output had geometric W | strict/native/hydrostatic | `resolve_omega()` | unit + real hydrostatic GRIB2 smoke |
| Time encoding | technical epoch | same canonical elapsed time | `processing/time.py` | unit/round-trip |
| Missing values | finite checks | same | canonical validation/bitmap | unit path |
| Output splitting | historical per-time combined | selectable | common layout function | round-trip tests |

The synthetic writer comparison uses the same canonical arrays, grid, times and exact hPa-representable Pa levels. All nine decoded field/level pairs had maximum absolute difference 0 with identical 24-bit simple packing. Results are in `validation/grib1_vs_grib2_parity.csv`.

The Venus5 benchmark keeps 20 integer-Pa levels in HDF5→GRIB2, then the
GRIB2→GRIB1 adapter derives and interpolates to the same 17 exact hPa surfaces
as the direct HDF5→GRIB1 route. Direct and adapter-derived GRIB1 each contain
561 messages. All comparisons pass at `0.002`; maximum absolute difference is
`0.00162506104`. The nonzero difference includes the GRIB2 route's extra
source-float→integer-Pa interpolation and packing. Products are outside Git at
`/home/malkouka/THOR_POE_HOST/venus_5_fileconversions/`.
