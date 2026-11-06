"""Exploitation d'un balayage en fréquence : ROS, coefficient de réflexion, résonances, bandes
passantes, et gain avant/arrière dans une direction fixe.

Toutes les grandeurs dépendant de l'impédance de référence z0 sont calculées ici (et non dans
l'interface) : changer z0 revient à relancer l'analyse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from itertools import pairwise

from .model import AntennaModel, RadiationGrid
from .results import FrequencyResult, SimulationResult
from .simulate import simulate

SWR_THRESHOLDS = (2.0, 1.5)
NO_GAIN_DB = -999.0  # NEC note -999.99 dB les directions sans rayonnement
_SWR_CAP = 1e6  # ROS « infini » plafonné pour l'interpolation


def reflection(z: complex, z0: float) -> complex:
    """Coefficient de réflexion Γ = (Z − Z0) / (Z + Z0)."""
    return (z - z0) / (z + z0)


def swr_from_gamma(g: complex) -> float:
    m = abs(g)
    return math.inf if m >= 1 else (1 + m) / (1 - m)


def swr_curve(result: SimulationResult, z0: float = 50.0) -> list[tuple[float, float]]:
    """Liste (fréquence MHz, ROS) pour le premier point d'alimentation de chaque fréquence."""
    return [
        (fr.frequency_mhz, fr.feedpoints[0].swr(z0)) for fr in result.frequencies if fr.feedpoints
    ]


def resonances(result: SimulationResult) -> list[float]:
    """Fréquences (MHz) où la réactance s'annule ou change de signe (interpolation linéaire)."""
    pts = [
        (fr.frequency_mhz, fr.feedpoints[0].impedance.imag)
        for fr in result.frequencies
        if fr.feedpoints
    ]
    out: list[float] = []
    for (f1, x1), (f2, x2) in pairwise(pts):
        if x1 == 0:
            out.append(f1)
        elif x1 * x2 < 0:
            out.append(f1 + (f2 - f1) * (-x1) / (x2 - x1))
    # le dernier point n'est jamais « f1 » dans la boucle : le tester à part
    if pts and pts[-1][1] == 0:
        out.append(pts[-1][0])
    return out


def resonance(result: SimulationResult) -> float | None:
    """Première fréquence de résonance, ou None."""
    found = resonances(result)
    return found[0] if found else None


@dataclass
class Band:
    """Plage de fréquences où le ROS reste sous un seuil, autour du ROS minimal."""

    threshold: float
    low_mhz: float
    high_mhz: float
    low_open: bool  # le ROS est encore sous le seuil au début du balayage : bande plus large
    high_open: bool  # idem à la fin du balayage

    @property
    def width_khz(self) -> float:
        return (self.high_mhz - self.low_mhz) * 1000


@dataclass
class SweepPoint:
    frequency_mhz: float
    impedance: complex
    gamma: complex
    swr: float  # math.inf si |Γ| = 1
    gain_db: float | None = None  # dans la direction demandée (avant)
    gain_back_db: float | None = None  # direction opposée en azimut (arrière)

    @property
    def front_to_back_db(self) -> float | None:
        if self.gain_db is None or self.gain_back_db is None:
            return None
        return self.gain_db - self.gain_back_db


@dataclass
class SweepSummary:
    z0: float
    min_swr: float | None
    min_swr_mhz: float | None
    resonances: list[float] = field(default_factory=list)
    bands: list[Band] = field(default_factory=list)  # un par seuil atteint


def _crossing(f1: float, s1: float, f2: float, s2: float, t: float) -> float:
    """Fréquence où le ROS franchit le seuil t entre deux points (interpolation linéaire)."""
    s1, s2 = min(s1, _SWR_CAP), min(s2, _SWR_CAP)
    if s1 == s2:
        return f1
    return f1 + (t - s1) * (f2 - f1) / (s2 - s1)


def find_band(freqs: list[float], swrs: list[float], threshold: float) -> Band | None:
    """Bande sous le seuil qui contient le ROS minimal ; None si le seuil n'est jamais atteint."""
    if not swrs:
        return None
    i_min = min(range(len(swrs)), key=swrs.__getitem__)
    if swrs[i_min] > threshold:
        return None
    lo = i_min
    while lo > 0 and swrs[lo - 1] <= threshold:
        lo -= 1
    hi = i_min
    while hi < len(swrs) - 1 and swrs[hi + 1] <= threshold:
        hi += 1
    low = (
        freqs[lo]
        if lo == 0
        else _crossing(freqs[lo - 1], swrs[lo - 1], freqs[lo], swrs[lo], threshold)
    )
    high = (
        freqs[hi]
        if hi == len(swrs) - 1
        else _crossing(freqs[hi], swrs[hi], freqs[hi + 1], swrs[hi + 1], threshold)
    )
    return Band(threshold, low, high, low_open=lo == 0, high_open=hi == len(swrs) - 1)


def _gains(fr: FrequencyResult, phi: float) -> tuple[float | None, float | None]:
    """Gain (dBi) vers phi et vers phi + 180°, dans le diagramme réduit de cette fréquence."""

    def at(target: float) -> float | None:
        for p in fr.pattern:
            if abs((p.phi - target + 180) % 360 - 180) < 1e-6:
                return p.gain_total_db if p.gain_total_db > NO_GAIN_DB else None
        return None

    return at(phi), at(phi + 180)


def analyze_sweep(
    result: SimulationResult,
    z0: float = 50.0,
    direction_phi: float | None = None,
) -> tuple[list[SweepPoint], SweepSummary]:
    """Points et résumé d'un balayage (premier point d'alimentation de chaque fréquence).

    `direction_phi` : azimut de la direction avant si le balayage contient le diagramme réduit
    produit par `simulate_sweep` ; on en tire gain avant, gain arrière et AV/AR.
    """
    if z0 <= 0:
        raise ValueError("z0 doit être > 0")
    points: list[SweepPoint] = []
    for fr in result.frequencies:
        if not fr.feedpoints:
            continue
        z = fr.feedpoints[0].impedance
        g = reflection(z, z0)
        front, back = _gains(fr, direction_phi) if direction_phi is not None else (None, None)
        points.append(SweepPoint(fr.frequency_mhz, z, g, swr_from_gamma(g), front, back))

    freqs = [p.frequency_mhz for p in points]
    swrs = [p.swr for p in points]
    best = min(points, key=lambda p: p.swr, default=None)
    summary = SweepSummary(
        z0=z0,
        min_swr=best.swr if best else None,
        min_swr_mhz=best.frequency_mhz if best else None,
        resonances=resonances(result),
        bands=[b for t in SWR_THRESHOLDS if (b := find_band(freqs, swrs, t)) is not None],
    )
    return points, summary


def simulate_sweep(
    model: AntennaModel,
    z0: float = 50.0,
    direction: tuple[float, float] | None = None,
    timeout: float = 120.0,
) -> tuple[SimulationResult, list[SweepPoint], SweepSummary]:
    """Balayage du modèle, avec gain avant/arrière si une direction (θ, φ en degrés) est donnée.

    Renvoie aussi le résultat brut (toutes les sources d'un modèle importé, par exemple).

    Le diagramme est réduit à 2 directions par fréquence (θ, φ) et (θ, φ + 180°) : le calcul
    reste léger même sur 201 fréquences.
    """
    if direction is None:
        run = replace(model, pattern=None)
        res = simulate(run, timeout=timeout)
        return (res, *analyze_sweep(res, z0))
    theta, phi = direction
    grid = RadiationGrid(n_theta=1, n_phi=2, d_theta=0, d_phi=180, theta0=theta, phi0=phi)
    res = simulate(replace(model, pattern=grid), timeout=timeout)
    return (res, *analyze_sweep(res, z0, direction_phi=phi))
