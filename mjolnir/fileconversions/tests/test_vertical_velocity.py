import numpy as np
import pytest

from mjolnir_fileconversions.errors import ScientificMappingError
from mjolnir_fileconversions.processing.vertical_velocity import resolve_omega


def test_native_omega_is_not_converted_twice():
    omega = np.array([1.0, -2.0])
    result, method = resolve_omega(mode="strict", native_omega=omega, native_units="Pa s-1")
    assert np.array_equal(result, omega)
    assert method == "native pressure omega"


def test_hydrostatic_w_to_omega_uses_venus_gravity_and_sign():
    w = np.array([2.0, -3.0])
    rho = np.array([1.5, 0.5])
    omega, method = resolve_omega(
        mode="hydrostatic", geometric_w=w, density=rho, gravity_m_s2=8.87
    )
    assert np.allclose(omega, -rho * 8.87 * w)
    assert omega[0] < 0  # upward motion decreases pressure
    assert "omega=-rho*g*w" in method


def test_strict_mode_rejects_geometric_w_relabeling():
    with pytest.raises(ScientificMappingError, match="geometric"):
        resolve_omega(
            mode="strict", geometric_w=np.ones(2), density=np.ones(2), gravity_m_s2=8.87
        )
