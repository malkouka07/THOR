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

Use `--variables u v` with `--vertical-velocity-mode omit` when omega cannot be justified. `strict`, `native-omega`, `model-defined`, `hydrostatic` and `omit` are explicit physical modes. Output defaults to per-variable, no overwrite. Reports cover classification, stage detection, variable/pressure mapping and round-trip statistics.

`--config` supplies YAML defaults, with explicit CLI options winning. `--time-index/--time-indices` select filename source indices. An explicit `--planet-file` replaces companion discovery. An explicit `--grid-file` is accepted only when its independent regular coordinates agree with the processed product, preventing it from becoming a native-grid fallback or a second regrid.

Each HDF5 file is opened sequentially, while selected canonical time slices are concatenated in memory for deterministic ordering and output layout. Use `--test-mode`, `--max-files` and time-index selection to bound memory; a production long-run invocation must be sized deliberately.
