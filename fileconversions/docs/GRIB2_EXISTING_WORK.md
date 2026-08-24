# Existing GRIB2 work

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

The only complete prior GRIB2 conversion was located on `origin/replat`, commit `8fe5da7` (`Add RePLaT tools and last 100 Venus outputs`). The relevant files are:

* `replat_conversion_last100_50591_50690/scripts/convert_thor_to_replat.py`;
* `scripts/convert_standard_netcdf_to_grib2.sh`;
* `scripts/validate_replat_inputs.py`;
* 100 standard NetCDF and 100 GRIB2 products.

It consumes Mjolnir `regrid_height_venus_<index>.h5`, not native ico HDF5. It identifies U/V/W by names plus upstream knowledge; reconstructs instantaneous pressure as `Rho*Rd*Temperature`; remaps the cell-centred 4° grid periodically to `-90..90, 0..356`; uses zero U/V at exact poles and nearest-ring zonal means for scalars/W; derives common integer Pa levels; interpolates columns linearly in `log(p)` with no extrapolation; and writes `time,level,latitude,longitude` NetCDF. Time comes from native companion `simulation_time`; the historical technical epoch was year 1.

CDO maps eastward wind to GRIB2 0/2/2, northward wind to 0/2/3, and geometric W to 0/2/9. It does not claim W is omega. The GRIB2 files contain finite 46×90 fields and 20 pressure levels. Python validation and CDO reopen checks were present. The committed baseline here was independently regenerated from `replat_venus_00050591.grib2` and confirms `wz` units `m s**-1`.

Reusable without numerical change: regular target construction, coordinate sorting, periodic bilinear interior interpolation, explicit pole convention, integer-Pa/log(p) pressure work, canonical dimension order, statistics and no-overwrite behavior. Refactored: those pieces now operate as package functions and feed both writers. Corrected/strengthened: structural HDF5 classification; stage/double-processing detection; explicit physical omega modes; native ecCodes writing; GRIB1 pressure policies; complete mapping/sidecar reports.

The old GRIB2 numerical product is not claimed equal to the new omega product: old message 0/2/9 is geometric W; the new optional 0/2/8 is hydrostatic omega. U/V and shared preprocessing algorithms are preserved, but a full old/new real numerical comparison was not run for the absent 50,591–50,690 source HDF5 set.
