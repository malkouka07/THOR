# Input inspection

Generated with OpenAI Codex assistance
Review status: pending manual review by Márkó

The requested `/home/malkouka/THOR_POE_HOST/venus_5_long_results` was not present in this workspace. The available read-only representative set is `/home/malkouka/THOR_POE_HOST/venus_5_long_benchmark`, with indices 0–10.

The committed inventory `validation/hdf5_input_classification.csv` records every HDF5 file. Summary:

* 22 native files (`esp_output_venus_*.h5`, including VDS): flattened ico-grid `Mh`, `Wh`, `Pressure`, no independent regular latitude/longitude;
* 22 Mjolnir products: 11 `pgrid_0_10_1/regrid_venus_*.h5` and 11 `regrid_height_venus_*.h5`;
* three metadata/grid files: auxiliary topology, output grid and planet parameters.

Representative processed pressure-grid file `pgrid_0_10_1/regrid_venus_1.h5` is 15,252,563 bytes. It has one-dimensional `Latitude(45)=-88..88`, `Longitude(90)=0..356`, `Pressure(20)=99578.66..4.097814 Pa`, and chunked/gzip `U`, `V`, `W`, `Rho`, `Temperature`, `Pressure_mean` arrays shaped `(45,90,20)`. HDF5 attributes are absent; physical meaning is established from Mjolnir source and the prior GRIB2 work.

Representative height-grid file `regrid_height_venus_1.h5` is 15,265,928 bytes. It has `Altitude(20)=25..47964.28 m`, the same horizontal grid and fields, but no instantaneous `Pressure`; downstream instantaneous pressure is `Rho*Rd*Temperature`, matching prior work.

Representative native `esp_output_venus_1.h5` is 11,680,668 bytes. It stores flattened `Mh(153720)`, `Wh(53802)`, `Rho(51240)`, `Pressure(51240)` and `simulation_time=86400 s`. It is inspected only for provenance/time and is rejected as a conversion input.

`esp_output_planet_venus.h5` supplies radius 6,051,800 m, gravity 8.87 m/s², rotation rate −2.992e−7 s⁻¹, `Rd=188.9 J/(kg K)`, `Cp=850 J/(kg K)` and `P_Ref=100000 Pa`. `config_copy.0` and the planet HDF5 confirm Venus-specific configuration.

Observed processed units inferred from upstream definitions: U/V/W are m/s; `W` is positive-up geometric layer-centre velocity. Pressure and `Pressure_mean` are Pa. No Pa/s native omega dataset was found. Missing/fill attributes are absent and representative arrays were finite. Remaining uncertainty: the hydrostatic `-rho*g*w` downstream mode is an approximation and has not been established as THOR's exact material `Dp/Dt`.
