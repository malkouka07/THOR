# Mjolnir native → processed HDF5 provenance

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

The authoritative implementation inspected is `origin/mjolnir_advance` commit `f6289cf`, file `mjolnir/hamarr.py`.

* Entry point: `mjolnir/regrid.py` calls `hamarr.regrid()`.
* `create_rg_map()` builds a cell-centred regular grid with angular resolution `4/2**(glevel-4)` degrees. For `glevel=4`, latitude is −88..88 and longitude 0..356.
* It maps each regular-grid point to an enclosing native spherical triangle. CUDA `find_nearest` plus Möller–Trumbore barycentric `calc_weights` produces `regrid_map.npz`; fields use the same weights.
* `regrid()` reads one native time at a time. It forms layer-centre `W` by interface interpolation of `Wh`, then divides by `Rho`; therefore W is geometric m/s, positive in the model radial/upward direction.
* Native Cartesian horizontal momentum is converted before interpolation: `U=(-Mh_x sin(lon)+Mh_y cos(lon))/Rho`; `V=(-Mh_x sin(lat)cos(lon)-Mh_y sin(lat)sin(lon)+Mh_z cos(lat))/Rho`. The written U/V are already geographic zonal/meridional velocities. Downstream code must not rotate them again.
* Instantaneous temperature is `Pressure/(Rd*Rho)`. `Pressure`, U/V/W, density and other fields are horizontally interpolated to `(latitude,longitude,level)`.
* `vertical_regrid_field()` linearly interpolates height-grid columns to a common pressure grid created by `define_Pgrid()`. This upstream interpolation is already complete in `pgrid_*/regrid_*.h5`; it is not repeated unless integer-Pa target values genuinely differ.
* Height products are `regrid_height_<simulation>_<index>.h5`; pressure products are `<pgrid folder>/regrid_<simulation>_<index>.h5`. `_write_regrid_h5()` uses gzip and atomic temporary replacement as added in `f6289cf`.
* The upstream grid excludes exact poles. Downstream pole construction is therefore still required for the requested GRIB target.
* Longitude is increasing `[0,360)`. Stored arrays are latitude, longitude, vertical level. No fill/missing attributes are written; pressure-grid surface masking may produce NaN when surface masking is active.
* Model time stays in the companion native file as `simulation_time` seconds; processed files do not store it.

The converter detects these completed stages from structure and records them in `processing_stage_detection.csv`. It skips native interpolation, vector rotation, longitude normalization when already normalized, and pressure interpolation when coordinates already match. Native files are never passed to a writer.

An upstream regeneration was not run: this path requires PyCUDA/CUDA, while matching processed products already exist. `validation/mjolnir_hdf5_regeneration_check.csv` records that status without claiming equivalence.
