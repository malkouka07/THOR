# GRIB2 migration map

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

| original_path | original_branch_or_commit | original_purpose | new_path | reused_unchanged | refactored | Codex_modified | compatibility_notes |
|---|---|---|---|---|---|---|---|
| `.../convert_thor_to_replat.py` | `origin/replat@8fe5da7` | processed HDF5 → canonical NetCDF | `src/.../readers/hdf5_reader.py`, `processing/grid.py`, `pressure.py` | numerical conventions | yes | yes | Native inputs remain forbidden; strict stage detection added. |
| `.../convert_standard_netcdf_to_grib2.sh` | `origin/replat@8fe5da7` | CDO GRIB2 encoding | `writers/grib2_writer_adapter.py` | WMO parameter mapping | yes | yes | Python ecCodes backend; omega is 0/2/8, geometric W is not silently emitted. |
| `.../validate_replat_inputs.py` | `origin/replat@8fe5da7` | grid/unit/statistics checks | `validation/` | validation intent | yes | yes | Both editions, round-trip and parity now supported. |
| historical entry points | `origin/replat@8fe5da7` | one fixed 100-file batch | `scripts/hdf5_to_grib2.py` | no | yes | yes | Universal paths/options; original branch remains intact. |
