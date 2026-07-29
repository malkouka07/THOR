# THOR Venus → RePLaT conversion, indices 50591–50690

This directory contains the reproducible THOR-to-RePLaT conversion tools and
the final 100 consecutive converted outputs from the
`venus_5_long_results` run.

## Contents

```text
replat_conversion_last100_50591_50690/
├── README.md
├── scripts/
│   ├── convert_thor_to_replat.py
│   ├── convert_standard_netcdf_to_grib2.sh
│   └── validate_replat_inputs.py
├── standard_netcdf/
│   └── replat_venus_00050591.nc … replat_venus_00050690.nc
└── grib2/
    └── replat_venus_00050591.grib2 … replat_venus_00050690.grib2
```

Reports, conversion logs, validation artifacts, temporary files, and the
earlier index-50000 test output are intentionally excluded from this branch.

## Conversion summary

- Source files: `regrid_height_venus_50591.h5` through
  `regrid_height_venus_50690.h5`.
- Variables:
  - `U` → `eastward_wind`
  - `V` → `northward_wind`
  - geometric `W` → `upward_air_velocity`
- Target grid: regular 4° latitude–longitude grid, 46 × 90 points.
- Latitude: `-90,-86,…,90`.
- Longitude: `0,4,…,356`.
- Dimension order: `time, level, latitude, longitude`.
- Pole treatment:
  - `U=V=0` at the exact poles;
  - scalar fields and `W` use the nearest latitude-ring zonal mean.
- Pressure: reconstructed as `Rho * Rd * Temperature`.
- Vertical interpolation: linear in `log(p)`, without extrapolation.
- Time cadence: 86400 seconds, read from the matching raw THOR outputs.
- Vertical velocity was kept as geometric `W` in `m s-1`; it was not
  converted to pressure velocity (`omega`).

All files share these 20 integer pressure levels in Pa, ordered from the
surface upward:

```text
97895, 97478, 96645, 95012, 91913,
86366, 77366, 64758, 50077, 35957,
24403, 15945, 10093, 6134, 3527,
1887, 921, 402, 157, 65
```

The common boundary levels were determined by scanning all 100 inputs. The
earlier test-only range of `97916…61 Pa` would have required extrapolation in
12 files, so all 100 outputs were generated consistently on the safe
`97895…65 Pa` range.

## GRIB2 parameters

- Eastward wind: WMO discipline/category/number `0/2/2`.
- Northward wind: `0/2/3`.
- Geometric vertical velocity: `0/2/9`.

## Validation

The complete 100-file batch was checked with
`scripts/validate_replat_inputs.py`:

- 100 NetCDF files and 100 GRIB2 files were present and non-empty;
- every NetCDF field had shape `1 × 20 × 46 × 90`;
- all files used the same pressure levels;
- the time sequence was strictly increasing at a uniform 86400-second cadence;
- latitude, longitude, poles, dimensions, units, and finite values passed;
- all GRIB2 files were readable with CDO;
- result: **0 errors and 0 warnings**.

The generated validation report is deliberately not committed, per the
data-publication scope of this branch.

## Software used

- Python 3
- NumPy
- SciPy
- h5py
- xarray
- netCDF4
- CDO 2.4.0 with ecCodes 2.34.1

The scripts protect existing outputs unless overwrite is requested explicitly.
The NetCDF converter writes through a temporary `.partial` file and renames it
only after a successful write.
