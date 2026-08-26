# Manual review checklist

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

* [ ] The GRIB2 preprocessing source is correctly identified
* [ ] GRIB1 and GRIB2 use the same canonical fields
* [ ] Native HDF5 rejection is manually verified
* [ ] Double interpolation and vector rotation safeguards are reviewed
* [ ] Pole handling is scientifically reviewed
* [ ] Pressure-level mapping is manually reviewed
* [ ] The 17-level Venus5 hPa target and log(p) interpolation are reviewed
* [ ] Dropped duplicate sub-1-hPa source levels are accepted
* [ ] Legacy label-only `hpa-rounded` is excluded from production
* [ ] Omega physical definition and sign are reviewed
* [ ] Venus gravity provenance is verified
* [ ] GRIB1 parameter identifiers 33/34/39 are independently checked
* [ ] WMO omega `39.2` versus ECMWF local omega `135.128` is accepted
* [ ] GRIB1 centre/table/level encoding matches the target consumer
* [ ] Real-data round-trip validation is reviewed
* [ ] GRIB1–GRIB2 parity is reviewed
* [ ] Optional wgrib/grib_dump validation is run in a richer environment
* [ ] Full long-run processing may be authorized
