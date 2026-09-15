# Scientific assumptions

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

Venus parameters are read from the companion planet HDF5, not Earth defaults: radius 6,051,800 m; surface gravity 8.87 m/s²; rotation −2.992e−7 s⁻¹; gas constant 188.9 J/(kg K); heat capacity 850 J/(kg K); reference pressure 100,000 Pa. Source: `esp_output_planet_venus.h5`; values agree with `config_copy.0` where represented.

Processed U/V are geographic winds because Mjolnir projects native Cartesian momentum into local east/north and divides by density before writing. W is layer-centre radial/geometric velocity in m/s because Mjolnir interpolates interface `Wh` then divides by density. No native Pa/s omega was found.

`hydrostatic` mode assumes `omega≈-rho*g*w`, W positive upward and standard omega positive toward increasing pressure. Density and W are collocated before multiplication. This is a hydrostatic approximation and may omit material horizontal pressure tendency/nonhydrostatic effects; it is not presented as THOR's exact `Dp/Dt`. Strict mode therefore remains the default.

The exact pole has no unique local east/north basis. Zero U/V is a documented regularity convention inherited from the prior GRIB2 flow, not a claim that every physical polar vector must vanish. Scalar/omega poles use a zonal ring mean.

The GRIB date is a technical epoch plus model elapsed time and is not terrestrial observation time. Venus metadata not representable in GRIB1 is retained in JSON sidecars.

GRIB1 pressure targets are selected from the source profile at the nearest
positive integer hPa inside the non-extrapolating common pressure range. Exact
half-hPa ties go toward lower pressure and duplicate coordinates are omitted.
Fields are evaluated at emitted targets by piecewise-linear interpolation in
`log(p)`; pressure labels are never substituted for this evaluation.
