import h5py
import xarray as xr
import numpy as np
import sys

infile = sys.argv[1]
outfile = sys.argv[2]

with h5py.File(infile, "r") as f:

    lat = f["Latitude"][:]
    lon = f["Longitude"][:]
    pressure = f["Pressure"][:]

    # model layer index
    levels = np.arange(len(pressure))

    data_vars = {}

    for name in f.keys():

        if name in ["Latitude", "Longitude", "Pressure"]:
            continue

        arr = f[name][:]

        # 3D fields (lat,lon,level) → (level,lat,lon)
        if arr.ndim == 3:
            arr = np.transpose(arr, (2, 0, 1))
            data_vars[name] = (("level", "lat", "lon"), arr)

        # 2D fields (lat,lon)
        elif arr.ndim == 2:
            data_vars[name] = (("lat", "lon"), arr)

    ds = xr.Dataset(
        data_vars,
        coords={
            "lat": ("lat", lat, {
                "standard_name": "latitude",
                "units": "degrees_north",
                "axis": "Y"
            }),
            "lon": ("lon", lon, {
                "standard_name": "longitude",
                "units": "degrees_east",
                "axis": "X"
            }),

            # model layer index
            "level": ("level", levels, {
                "long_name": "model_level_number",
                "axis": "Z"
            }),

            # pressure coordinate attached to level
            "pressure": ("level", pressure, {
                "standard_name": "air_pressure",
                "units": "Pa",
                "positive": "down"
            })
        }
    )

    ds.attrs["Conventions"] = "CF-1.8"

    ds.to_netcdf(outfile)

print("Converted:", outfile)