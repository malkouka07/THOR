# Git and data layout

This fork uses two remotes:

- `upstream`: `https://github.com/exoclime/THOR.git`, the original THOR project;
- `origin`: `https://github.com/malkouka07/THOR.git`, Márkó's fork.

General Mjolnir development is maintained on `mjolnir_advance`. The focused
GRIB1 ordering, temperature and reconstruction-report work branches from it as
`grib1work`. The fork's `main` branch remains the clean base derived from
upstream THOR.

## Source layout

The primary local checkout is:

```text
/home/malkouka/THOR
```

Mjolnir extensions live under `mjolnir/`. The unified HDF5, NetCDF, GRIB1 and
GRIB2 conversion package is:

```text
/home/malkouka/THOR/mjolnir/fileconversions
```

Its implementation, command-line scripts, tests, documentation and compact
validation evidence are tracked by Git. Generated model and conversion data
are not tracked.

## Local conversion data

Reusable local inputs and generated products live outside the Git checkout:

```text
/home/malkouka/THOR_conversion_data/
├── inputs/venus_5_long_benchmark/
├── outputs/venus_5_fileconversions/
└── tests/
    ├── codex_test_outputs/
    ├── grib1work_smoke/
    ├── grib1work_smoke_grib2/
    └── grib1work_smoke_adapter/
```

This separation prevents accidental commits of large HDF5/GRIB products and
keeps conversion data visible when the POE server is mounted.

## POE mountpoint

`/home/malkouka/THOR_POE_HOST` is reserved exclusively as the SSHFS mountpoint
for:

```text
cserpakm@poe.elte.hu:/home/cserpakm/THOR_files
```

Do not place local repositories or irreplaceable local data underneath this
directory. An active mount hides the underlying local contents, and a stale
SSHFS connection can produce misleading I/O errors.

## Branch policy

- `upstream/main`: original THOR reference;
- `origin/main`: base branch of the personal fork;
- `origin/mjolnir_advance`: integrated Mjolnir/conversion base;
- `origin/grib1work`: temperature, ascending-pressure and original-HDF5
  reconstruction-report development based on `mjolnir_advance`.

The former `fileconversions` feature branch was merged into
`mjolnir_advance`. The former `replat` and `replat-motus-compat` publication
branches were retired after their reusable behavior and provenance had been
captured in the integrated converter.

Simulation results, generated initial-condition HDF5 files, virtual
environments, caches, compiled products and conversion outputs must remain
outside Git or be covered by `.gitignore`.
