import numpy as np

from mjolnir_fileconversions.processing.grid import (
    horizontal_remap,
    normalize_source_grid,
    target_regular_grid,
)


def test_target_grid_contains_poles_without_360():
    lat, lon = target_regular_grid(4, 4)
    assert lat.shape == (46,)
    assert lon.shape == (90,)
    assert (lat[0], lat[-1]) == (-90, 90)
    assert (lon[0], lon[-1]) == (0, 356)
    assert np.allclose(np.diff(lat), 4)
    assert np.allclose(np.diff(lon), 4)


def test_normalize_grid_sorts_both_axes_and_field():
    lat = np.array([10.0, -10.0])
    lon = np.array([180.0, -90.0, 0.0])
    field = np.arange(6).reshape(2, 3, 1)
    out_lat, out_lon, [out] = normalize_source_grid(lat, lon, [field])
    assert np.array_equal(out_lat, [-10, 10])
    assert np.array_equal(out_lon, [0, 180, 270])
    assert out[:, :, 0].tolist() == [[5, 3, 4], [2, 0, 1]]


def test_scalar_poles_are_zonal_means_and_vectors_are_zero():
    source_lat = np.array([-60.0, 0.0, 60.0])
    source_lon = np.array([0.0, 90.0, 180.0, 270.0])
    target_lat, target_lon = target_regular_grid(30, 90)
    field = np.arange(12, dtype=float).reshape(3, 4, 1)
    scalar = horizontal_remap(
        field, source_lat, source_lon, target_lat, target_lon, pole_kind="scalar"
    )
    vector = horizontal_remap(
        field, source_lat, source_lon, target_lat, target_lon, pole_kind="horizontal_vector"
    )
    assert np.allclose(scalar[0, :, 0], np.mean(field[0]))
    assert np.allclose(scalar[-1, :, 0], np.mean(field[-1]))
    assert np.all(vector[[0, -1]] == 0)
    assert not np.isnan(scalar).any()
