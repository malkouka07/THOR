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

Real HDF5→GRIB2 produced 60 messages from the same canonical path; direct round-trip maximum absolute error was `1.9073486328125e-06`. Full-level parity is blocked before GRIB1 writing because Venus levels such as 99,578 Pa are not exact WMO GRIB1 hPa levels. This is an expected strict-format limitation, not a parity success. The real HDF5→GRIB2 output and strict failure reports are stored outside Git.
