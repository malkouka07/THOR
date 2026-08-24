# Manual review checklist

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

* [ ] The GRIB2 preprocessing source is correctly identified
* [ ] GRIB1 and GRIB2 use the same canonical fields
* [ ] Native HDF5 rejection is manually verified
* [ ] Double interpolation and vector rotation safeguards are reviewed
* [ ] Pole handling is scientifically reviewed
* [ ] Pressure-level mapping is manually reviewed
* [ ] GRIB1 strict/hPa/ecmwf level policies are reviewed
* [ ] Omega physical definition and sign are reviewed
* [ ] Venus gravity provenance is verified
* [ ] GRIB1 parameter identifiers 33/34/39 are independently checked
* [ ] GRIB1 centre/table/level encoding matches the target consumer
* [ ] Real-data round-trip validation is reviewed
* [ ] GRIB1–GRIB2 parity is reviewed
* [ ] Optional wgrib/grib_dump validation is run in a richer environment
* [ ] Full long-run processing may be authorized
