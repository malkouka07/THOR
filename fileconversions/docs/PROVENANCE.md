# Provenance

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

| Component | Prior source | Action |
|---|---|---|
| Native → regular/pressure Mjolnir processing | `origin/mjolnir_advance@f6289cf`, `mjolnir/hamarr.py` | inspected and documented; not copied or reimplemented |
| Existing GRIB2 preparation | `origin/replat@8fe5da7` conversion/validation scripts | algorithms migrated/refactored into shared modules; generated files not copied |
| Canonical data model/input classification/stage detection | none | new, Codex-assisted |
| Shared grid/pressure/omega/time modules | prior GRIB2 concepts plus upstream definitions | refactored and materially strengthened, Codex-assisted |
| GRIB1 writer and validator | none | new, Codex-assisted |
| GRIB2 ecCodes writer adapter | prior CDO parameter mapping | new implementation, Codex-assisted |
| GRIB2→GRIB1 and NetCDF→GRIB1 | none | new, Codex-assisted |
| Tests/docs/reports | prior validator supplied some statistical concepts | new or substantially modified, Codex-assisted |

No existing file is represented as wholly authored by Codex. Historical commits retain their original authorship. All new products remain pending manual review by Márkó.
