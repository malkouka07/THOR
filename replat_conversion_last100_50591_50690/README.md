> **AI assistance and review notice:** The code and documentation in this
> directory were drafted with the assistance of OpenAI Codex, an AI coding
> agent based on GPT-5. They are currently being reviewed by `malkouka07`.

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
│   ├── convert_standard_netcdf_to_netcdf3_classic.sh
│   └── validate_replat_inputs.py
├── standard_netcdf/
│   └── replat_venus_00050591.nc … replat_venus_00050690.nc
├── grib2/
│   └── replat_venus_00050591.grib2 … replat_venus_00050690.grib2
└── motus_netcdf3_classic/
    └── replat_venus_00050591_motus_nc3_classic.nc
        … replat_venus_00050690_motus_nc3_classic.nc
```

Reports, conversion logs, validation artifacts, temporary files, and the
earlier index-50000 test output are intentionally excluded from this branch.

## Motus compatibility

The original `*.grib2` files are valid GRIB edition 2 files. They open with
Panoply's current release and were read successfully with CDO 2.4.0 linked to
ecCodes 2.34.1. The `Unsupported file type` result on Motus therefore points
to the installed CDO build lacking GRIB2/ecCodes support, rather than to a
damaged file. An older Panoply/netCDF-Java reader can fail for the same
version-dependent reason.

The `wgrib` command is a GRIB1-era tool and is not a valid test for these
GRIB2 files. `wgrib2` would be the matching command, but it is not installed
on Motus and is not required for the compatibility files supplied here.
There is no need to update the server operating system.

Two read-only checks can distinguish a Motus software limitation from a
damaged transfer:

```bash
cdo -V
sha256sum replat_venus_00050591.grib2
```

The CDO output must list `grb2` among its `CDI file types` to read GRIB2. The
expected SHA-256 value for the original file is:

```text
d47e7ed22319f2397765fe38ba02e32e7d10cac987e8666111442f91c3ab6e47
```

If that checksum differs on Motus, the copied file is incomplete or changed.
If it matches but CDO still reports `Unsupported file type`, the Motus CDO
build is the problem.

Use the files in `motus_netcdf3_classic/` on Motus. They use the original
NetCDF3 classic/CDF-1 format, which avoids both GRIB2/ecCodes and
NetCDF4/HDF5 dependencies:

```bash
cdo sinfo replat_venus_00050591_motus_nc3_classic.nc
```

The same `.nc` file can be opened directly in Panoply. To recreate the whole
directory from the canonical NetCDF4 files:

```bash
scripts/convert_standard_netcdf_to_netcdf3_classic.sh \
    standard_netcdf motus_netcdf3_classic
```

A GRIB1 set is deliberately not included. A trial conversion changed the
required pressure coordinates—for example, `97895 Pa` became `97900 Pa`—and
lost the unambiguous wind-variable identifiers. Such files would be easier
for old software to open but would no longer be equivalent RePLaT inputs.

Technical background:

- The [CDO manual](https://code.mpimet.mpg.de/projects/cdo/embedded/cdo.pdf)
  states that GRIB2 is available only when CDO is built with ecCodes support.
- NOAA documents
  [`wgrib2` as the GRIB2 utility](https://www.cpc.ncep.noaa.gov/products/wesley/wgrib2/).
- Unidata documents
  [NetCDF classic as the original CDF-1 format](https://docs.unidata.ucar.edu/netcdf/NUG/netcdf_introduction.html).

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
- all 100 Motus files have the NetCDF3 classic `CDF-1` signature;
- CDO `diffn` found no decoded value or metadata differences between each
  Motus file and its canonical NetCDF counterpart;
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

> **AI assistance and review notice:** The code and documentation in this
> directory were drafted with the assistance of OpenAI Codex, an AI coding
> agent based on GPT-5. They are currently being reviewed by `malkouka07`.
