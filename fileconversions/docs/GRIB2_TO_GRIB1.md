# GRIB2 → GRIB1

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

`scripts/grib2_to_grib1.py` iterates ecCodes messages. For each it records edition, discipline/category/number, names/units, level, valid time, grid, packing, bitmap, centre and tables; decodes coordinates/values; maps only U, V and pressure omega; creates a fresh GRIB1 message; and reopens output.

It never toggles an edition key. GRIB2 0/2/9 geometric W is unsupported rather than relabeled as GRIB1 pressure omega. Default `--on-unsupported error`; explicit skip is reported. GRIB2 fixed-surface scaled values are used to preserve exact Pa metadata even when ecCodes' convenience `level` is displayed in hPa.

GRIB1 level policies and output layouts match the HDF5 converter. YAML defaults and zero-based logical `--time-index/--time-indices` selection are supported. The default strict conversion of the historical Venus GRIB2 sample blocks on 97,895 Pa; the newly migrated real pressure-grid sample blocks on 99,578 Pa. Both retain explicit mapping information and leave no partial GRIB1.
