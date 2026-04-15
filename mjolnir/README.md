# Mjolnir

> Note: The code in this folder was drafted by Cserpák Mihály Márkó with the help of ChatGPT 5.4. The drafted code is still under review by the author.

`mjolnir` contains the post-processing, regridding, plotting, and export tools used with THOR output forked from the original upstream: https://github.com/exoclime/THOR.

This folder now includes:

- pressure-grid setup and regridding helpers
- a local wait-and-run automation helper
- a pressure-grid folder merger
- a THOR regridded HDF5 to CF-style NetCDF converter
- updated plotting helpers with lower-memory loading paths
`.

## Main workflow

From the THOR root directory, the typical workflow is:

1. Build a reference pressure grid with `mjolnir/pgrid.py`.
2. Regrid THOR output with `mjolnir/regrid.py`.
3. If regrids are split across several `pgrid_*` folders, merge them with `mjolnir/pgrid_merge.py`.
4. Plot with `mjolnir.py
4. If you need CF-compőliant Netcdf files, convert the regridded `.h5` files to `.nc` with `mjolnir/thor_h5_to_nc.py`. Mind that the conversion was not benchmarked yet, I do not take responsibility for corrupted results. 


## Important files

- `mjolnir.py`
  Main plotting entry point.

- `mjolnir_plot_helper.py`
  High-level plot selection and argument handling.

- `hamarr.py`
  Core THOR post-processing, regridding, and plotting backend.

- `pgrid.py`
  Creates the reference pressure grid text file used for pressure-coordinate regridding.

- `regrid.py`
  Produces `regrid_<simulation>_<index>.h5` and optionally `regrid_height_<simulation>_<index>.h5`.

- `pgrid_merge.py`
  Merges fragmented `pgrid_*` folders into one canonical folder.

- `wait_then_run.py`
  Waits for a long-running job to finish, then runs queued shell commands.

- `thor_h5_to_nc.py`
  Converts THOR regridded HDF5 output into CF-style NetCDF.

## `wait_then_run.py`

Purpose:
Run the next post-processing steps automatically after a long THOR job finishes.

Current behavior:

- waits for one or more PIDs to exit
- waits for one or more process-name regexes to disappear
- waits for one or more files to appear
- runs queued shell commands in order
- writes a timestamped log
- can continue past a failed command with `--keep-going`
- supports `--dry-run`

This is meant for unattended local workflows, for example:

- wait for `regrid.py` to finish
- run `pgrid_merge.py`
- then run `thor_h5_to_nc.py`

## `pgrid_merge.py`

Purpose:
Merge several fragmented pressure-grid folders into one consistent `pgrid_*` folder.

Current behavior:

- scans a results directory for `pgrid_*` folders
- groups files by time index
- chooses the largest duplicate file for each index
- reports missing index ranges
- writes a merge log
- can hard-link by default, or copy with `--copy`
- supports `--dry-run`
- can remove old source folders with `--delete-source-folders`

Use this when long THOR runs produced multiple partial `pgrid_*` folders that should behave as one clean dataset.

## `thor_h5_to_nc.py`

Purpose:
Convert mjolnir regridded THOR `.h5` files into CF-style `.nc` files.

Accepted inputs:

- `regrid_<simulation>_<index>.h5`
- `regrid_height_<simulation>_<index>.h5`

Not supported directly:

- raw THOR `esp_output_*.h5` files

Current behavior:

- detects pressure-coordinate or altitude-coordinate regrids automatically
- writes output by default into a sibling dedicated folder named `<input_dir>_nc`
- supports an explicit output file or `--output-dir`
- supports `--validate` to compare the written NetCDF back to the source HDF5
- uses no compression by default
- can enable compression with `--compression-level N`
- adds CF-1.8 style coordinate metadata
- adds selected variable attributes where they are known
- tries to auto-match the corresponding raw `esp_output_*.h5` file to carry over useful THOR metadata such as time step information

Example default path mapping:

- input: `pgrid_0_2000_1/regrid_venus_0.h5`
- output: `pgrid_0_2000_1_nc/regrid_venus_0.nc`

## NetCDF attributes

The NetCDF export currently adds:

- `Conventions = CF-1.8`
- standard `lat` and `lon` coordinate attributes
- either `pressure` or `altitude` as the vertical coordinate
- selected `standard_name`, `long_name`, and `units` attributes for common THOR variables
- global provenance fields such as input source path and detected simulation ID

This is intended to make the files easier to use in downstream software, while still keeping the export step simple and transparent.

## Plotter changes in this draft

The current local draft also includes plotter-side changes in `mjolnir_plot_helper.py` and `hamarr.py`.

These changes are intended to reduce memory pressure and make large regridded datasets easier to work with:

- lighter output-loading modes for time-only vertical plots
- a stream-oriented regrid reader for some plotting workflows
- lazy loading for regridded datasets instead of eagerly loading everything
- chunked averaging in some vertical plotting paths
- deferred PyCUDA loading so PyCUDA is only required when regridding is actually used
- support for simple post-transforms in plots, for example absolute-value velocity plotting

These plotting changes are still under active review.

## Dependencies

Practical notes for the current draft:

- `thor_h5_to_nc.py` uses `h5py`, `xarray`, and a NetCDF backend such as `netCDF4`
- `pgrid_merge.py` uses `numpy`
- regridding in `hamarr.py` still requires PyCUDA when the regridding kernels are used

## Status

This folder contains working research utilities, but the newly drafted additions and local modifications are still under review.

## Notes 
Mind that the radme file was drafted with the help of Chatgpt as well.
