# HDF5 ↔ decoded-GRIB1 reconstruction report

Generated with OpenAI Codex assistance  
Review status: pending manual review by Márkó

Every HDF5→GRIB1 run retains the normalized original HDF5 fields in memory,
writes GRIB1, reopens the resulting messages with ecCodes, and reconstructs the
decoded fields on the original HDF5 coordinates. The result is written to:

```text
reports/hdf5_grib1_reconstruction_statistics.csv
```

This is different from `roundtrip_statistics.csv`:

- `roundtrip_statistics.csv` compares decoded GRIB with the already remapped
  canonical writer input. It mainly measures GRIB packing/decoding error.
- `hdf5_grib1_reconstruction_statistics.csv` compares decoded GRIB with the
  original processed HDF5 values. It measures the combined effect of
  horizontal remapping, pressure interpolation, and GRIB packing.

## Reconstruction operation

For each variable and valid time, decoded messages are matched by semantic
`(variable, valid time, pressure)` keys, never by record number. The pressure
surfaces are then:

1. periodically bilinearly interpolated from the GRIB latitude/longitude grid
   back to the original HDF5 latitude/longitude grid;
2. linearly interpolated in `log(p)` from decoded GRIB pressure surfaces back
   to each original HDF5 pressure that lies inside the decoded pressure range;
3. subtracted using `difference = reconstructed GRIB1 - original HDF5`.

There is no vertical extrapolation. With the current Venus profile, decoded
GRIB covers `100…99500 Pa`; 15 of the 20 original levels are comparable. The
deepest source level (`99578.66 Pa`) and four levels below `100 Pa` are retained
as explicit `not_comparable` rows rather than silently omitted or extrapolated.

The comparison is repeated for four spatial regions:

- `all` — every original latitude;
- `interior` — latitudes whose interpolation does not use an exact GRIB pole;
- `south_pole_influenced` and `north_pole_influenced` — source rings bracketed
  by an exact GRIB pole.

The separation matters for U/V because the forward workflow deliberately sets
horizontal wind components to zero at the exact poles. Temperature and omega
are scalars and use the nearest source-ring zonal mean at the forward poles.

## Reading the CSV

Detail rows contain counts, original/reconstructed ranges, maximum absolute
difference, mean absolute difference, RMS difference, signed mean (bias),
relative RMS, correlation, and area-weighted diagnostics. `status=measured`
means a finite comparison was made; it is not a scientific pass/fail claim.

The final block contains `row_type=summary` rows. Each variable and region has
its own final summary because m/s, Pa/s, and K cannot be combined meaningfully.
The two requested headline values are:

- `maximum_absolute_difference` — the largest absolute pointwise difference;
- `mean_absolute_difference` — the average absolute pointwise difference,
  weighted by the number of compared values in every detail row.

Using absolute differences prevents positive and negative errors from
cancelling. The signed average remains available separately as
`mean_signed_difference` in detail rows.

The same final-summary convention is used for canonical packing round trips
and GRIB1/GRIB2 numerical parity. Classification, provenance and variable-map
CSVs do not compare numerical field values, so they do not receive invented
"difference" footers.

For point-by-point inspection, add `--reconstruction-netcdf`. This writes
`reports/hdf5_grib1_reconstruction_differences.nc` with original,
reconstructed, and signed-difference arrays on the HDF5 grid. Out-of-range
pressures are NaN by design.

## Temperature

The temperature reference is the instantaneous processed-HDF5 `Temperature`
field, interpreted as absolute air temperature in K. It is not
`Temperature_mean` and not potential temperature. GRIB1 uses WMO table 2
parameter 11 (`t`, ecCodes parameter 130); GRIB2 uses `0/0/0`.
