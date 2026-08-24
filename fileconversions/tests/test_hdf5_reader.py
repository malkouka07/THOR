from pathlib import Path

import h5py
import numpy as np
import pytest

from mjolnir_fileconversions.discovery import classify_hdf5
from mjolnir_fileconversions.errors import InputClassificationError
from mjolnir_fileconversions.readers.hdf5_reader import read_processed_hdf5


def _processed_tree(root: Path) -> Path:
    path = root / "regrid_test_1.h5"
    lat = np.array([-45.0, 0.0, 45.0])
    lon = np.array([0.0, 90.0, 180.0, 270.0])
    level = np.array([100000.0, 50000.0, 10000.0])
    shape = (lat.size, lon.size, level.size)
    with h5py.File(path, "w") as h:
        h["Latitude"] = lat
        h["Longitude"] = lon
        h["Pressure"] = level
        h["U"] = np.ones(shape)
        h["V"] = np.ones(shape) * 2
        h["W"] = np.ones(shape) * 0.1
        h["Rho"] = np.ones(shape) * 1.5
    with h5py.File(root / "esp_output_test_1.h5", "w") as h:
        h["simulation_time"] = np.array([86400.0])
    with h5py.File(root / "esp_output_planet_test.h5", "w") as h:
        h["A"] = np.array([6051800.0])
        h["Gravit"] = np.array([8.87])
        h["Omega"] = np.array([-2.992e-7])
        h["Rd"] = np.array([188.9])
        h["Cp"] = np.array([850.0])
        h["P_Ref"] = np.array([100000.0])
    return path


def test_processed_hdf5_classification_and_reader(tmp_path):
    path = _processed_tree(tmp_path)
    assert classify_hdf5(path).classification == "mjolnir_processed"
    dataset, mapping = read_processed_hdf5(
        path,
        variables=["u", "v", "omega"],
        lat_step=45,
        lon_step=90,
        vertical_velocity_mode="hydrostatic",
    )
    assert dataset.shape == (1, 3, 5, 4)
    assert dataset.planet.gravity_m_s2 == 8.87
    assert np.all(dataset.fields["omega"][:, :, 1:-1] == pytest.approx(-1.5 * 8.87 * 0.1))
    assert mapping[0].target_level_pa == 100000
    assert all("native-grid interpolation" in stage.skipped_as_already_completed for stage in dataset.stages)


def test_native_hdf5_is_rejected(tmp_path):
    path = tmp_path / "esp_output_test_1.h5"
    with h5py.File(path, "w") as h:
        h["Mh"] = np.zeros(30)
        h["Wh"] = np.zeros(12)
        h["Pressure"] = np.ones(10)
    assert classify_hdf5(path).classification == "native_icosahedral"
    with pytest.raises(InputClassificationError):
        read_processed_hdf5(path, variables=["u", "v"])


def test_explicit_regular_grid_is_cross_checked(tmp_path):
    path = _processed_tree(tmp_path)
    grid = tmp_path / "processed_grid.h5"
    with h5py.File(grid, "w") as handle:
        handle["Latitude"] = np.array([-45.0, 0.0, 45.0])
        handle["Longitude"] = np.array([0.0, 90.0, 180.0, 270.0])
    dataset, _ = read_processed_hdf5(
        path,
        variables=["u", "v"],
        lat_step=45,
        lon_step=90,
        grid_file=grid,
    )
    assert dataset.metadata["explicit_grid_file"] == str(grid.resolve())
