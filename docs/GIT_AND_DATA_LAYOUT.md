# Git and data layout

This fork uses two remotes:

- `upstream`: `https://github.com/exoclime/THOR.git`, the original THOR project;
- `origin`: `https://github.com/malkouka07/THOR.git`, Márkó's fork.

Development specific to this fork is maintained on `mjolnir_advance`. The
fork's `main` branch remains the clean base derived from upstream THOR.

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
└── tests/codex_test_outputs/
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
- `origin/mjolnir_advance`: active Mjolnir and conversion development.

The former `fileconversions` feature branch was merged into
`mjolnir_advance`. The former `replat` and `replat-motus-compat` publication
branches were retired after their reusable behavior and provenance had been
captured in the integrated converter.

Simulation results, generated initial-condition HDF5 files, virtual
environments, caches, compiled products and conversion outputs must remain
outside Git or be covered by `.gitignore`.
