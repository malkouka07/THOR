# Validation evidence in this directory

Generated with OpenAI Codex assistance  
Review status: pending manual review by Márkó

Most CSV files in this directory are preserved evidence from the earlier
`mjolnir_advance` three-variable benchmark at commit `704fb0e`. They describe
U, V and omega files written in the former descending pressure-message order.
They are retained for provenance and are **not** examples of the current
`grib1work` output schema.

Current conversions write fresh reports beside their generated data under the
chosen `<output-dir>/reports/`. Those reports include temperature, ascending
pressure-message validation, final per-variable difference summary rows, and
the HDF5↔decoded-GRIB1 reconstruction diagnostics. The current one-time real
smoke reports are outside Git at:

```text
/home/malkouka/THOR_conversion_data/tests/grib1work_smoke/reports/
```

`validation_report.md` distinguishes current test/smoke results from the
preserved full-run evidence. Regenerate the full 11-time benchmark after the
branch is committed before treating its sidecars or CSVs as current artifacts.
