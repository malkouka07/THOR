#!/usr/bin/env python3
"""
Writes a 1000-row Venus vertical profile to a text file.

Output columns (space-separated):
Height[m] Pressure[Pa] Rho[kg/m^3]

Pressure is log-linear between:
  z=50 km:  p = 0.12*1e4 hPa = 1200 hPa = 120000 Pa
  z=100 km: p = 0.032 hPa = 3.2 Pa

Density:
  rho = p / (Rspec * T), with CO2 Rspec = R/M (M=0.044 kg/mol)

Temperature profile (piecewise linear, Venus-like 50–100 km):
  (50 km, 348 K), (70 km, 230 K), (95 km, 165 K), (100 km, 161 K)
"""

from __future__ import annotations
import numpy as np
from pathlib import Path

def piecewise_linear_T(z_m: np.ndarray) -> np.ndarray:
    z_pts = np.array([50000.0, 70000.0, 95000.0, 100000.0], dtype=float)
    T_pts = np.array([348.0,    230.0,    165.0,    161.0   ], dtype=float)
    return np.interp(z_m, z_pts, T_pts)

def generate_profile(n: int = 1000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    z0, z1 = 50000.0, 100000.0   # meters
    p0, p1 = 120000.0, 3.2        # Pa

    R_univ = 8.314462618  # J/(mol K)
    M_co2  = 0.044        # kg/mol
    Rspec  = R_univ / M_co2

    z = np.linspace(z0, z1, n)  # inclusive
    ln_p = np.linspace(np.log(p0), np.log(p1), n)
    p = np.exp(ln_p)

    T = piecewise_linear_T(z)
    rho = p / (Rspec * T)

    return z, p, rho

def write_profile(path: str | Path, z: np.ndarray, p: np.ndarray, rho: np.ndarray) -> None:
    path = Path(path)
    with path.open("w", encoding="utf-8") as f:
        f.write("Height Pressure Rho\n")
        for zi, pi, rhoi in zip(z, p, rho):
            f.write(f"{zi:.6e} {pi:.6e} {rhoi:.6e}\n")

def main() -> None:
    out_file = "/home/malkouka/THOR/tools/Venus_20layers_from1bar.txt"
    z, p, rho = generate_profile(n=1000)
    write_profile(out_file, z, p, rho)
    print(f"Wrote {len(z)} rows to: {out_file}")

if __name__ == "__main__":
    main()


inp = "/home/malkouka/THOR/tools/Venus_20layers_from1bar.dat"   # your current file
out = "/home/malkouka/THOR/tools/Venus_20layers_from1bar.txt"     # THOR-ready file

data = np.loadtxt(inp, skiprows=1)
z_abs = data[:,0]
p = data[:,1]
rho = data[:,2]

z_rel = z_abs - 50000.0

# sanity
assert z_rel.min() >= -1e-6 and abs(z_rel.max()-50000.0) < 1e-2
assert np.all(np.diff(z_rel) > 0)
assert np.all(p > 0) and np.all(rho > 0)

with open(out, "w") as f:
    f.write("Height Pressure Rho\n")
    for zi, pi, ri in zip(z_rel, p, rho):
        f.write(f"{zi:.6e} {pi:.6e} {ri:.6e}\n")

print("Wrote:", out)
