# Mjolnir-processed HDF5 → GRIB1

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

`scripts/hdf5_to_grib1.py` accepts explicit files, directories or globs, but always enforces `--input-kind mjolnir-processed`. Verification requires independent regular latitude/longitude and geographic U/V-shaped data. Native `Mh/Wh` structure is rejected.

Pressure-grid `regrid_*.h5` is preferred by automatic discovery because Mjolnir has already completed vertical interpolation. Height-grid `regrid_height_*.h5` is also supported; pressure is reconstructed and fields receive one required downstream log-pressure interpolation. Both paths adjust the grid to include poles and never redo native vector rotation.

For GRIB1, the default `--pressure-level-policy hpa-aligned` derives exact
integer-hPa surfaces inside the source range and interpolates directly from the
original pressure coordinate. Use it with `--level-encoding strict`. This is a
real field interpolation, not the legacy `hpa-rounded` label-only mode. The
Venus5 target and production command are in [VENUS5_GRIB1.md](VENUS5_GRIB1.md).

The default variables are `u v omega temperature`. Temperature comes from the
instantaneous `Temperature` dataset and is encoded as absolute air temperature
in K (GRIB1 table 2 parameter 11). Use `--variables u v` with
`--vertical-velocity-mode omit` when omega or temperature is unavailable.
`strict`, `native-omega`, `model-defined`, `hydrostatic` and `omit` are explicit
physical modes. Output defaults to per-variable, no overwrite.

Reports cover classification, stage detection, variable/pressure mapping,
canonical packing round-trip statistics, and decoded GRIB1 reconstructed on
the original HDF5 coordinates. Difference CSVs end with per-variable maximum
and point-weighted mean absolute differences and their normalized percentages:
`100 × max(|E|) / max(|R|)` and `100 × sum(|E|) / sum(|R|)`. Packing
round trips use the canonical writer input as `R`; reconstruction uses only the
finite, pressure-comparable original HDF5 values. These are aggregate ratios,
not pointwise percentage errors, so zero-crossing winds and omega do not cause
division spikes. Zero reference and zero error gives `0%`; nonzero error against
a zero reference is `NaN`. Non-value classification, mapping, provenance,
pressure and structural CSVs do not receive these footers. See
[HDF5_GRIB1_RECONSTRUCTION.md](HDF5_GRIB1_RECONSTRUCTION.md).

`--config` supplies YAML defaults, with explicit CLI options winning. `--time-index/--time-indices` select filename source indices. An explicit `--planet-file` replaces companion discovery. An explicit `--grid-file` is accepted only when its independent regular coordinates agree with the processed product, preventing it from becoming a native-grid fallback or a second regrid.

Each HDF5 file is opened sequentially, while selected canonical time slices are concatenated in memory for deterministic ordering and output layout. Use `--test-mode`, `--max-files` and time-index selection to bound memory; a production long-run invocation must be sized deliberately.
