"""Diagramme de rayonnement à une fréquence : grille de calcul et analyse (coupes, AV/AR).

Conventions NEC : θ est compté depuis le zénith (0° = vers le haut, 90° = horizon) et φ depuis
l'axe +X, dans le sens trigonométrique. On présente l'élévation (90° − θ), plus parlante pour
un radioamateur (« angle de départ »).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .model import AntennaModel, FrequencySweep, Ground, RadiationGrid
from .results import FrequencyResult, PatternPoint
from .simulate import simulate

STEP_DEG = 2.0
# NEC note -999.99 dB les directions sans rayonnement (ex. sous le sol)
NO_GAIN_DB = -999.0


def pattern_grid(ground: Ground) -> RadiationGrid:
    """Grille au pas de 2° : demi-sphère supérieure avec sol, sphère entière sans."""
    n_phi = int(360 / STEP_DEG)  # 0 à 358° : 360° ferait doublon avec 0°
    theta_max = 90.0 if ground.kind != "free" else 180.0
    return RadiationGrid(
        n_theta=int(theta_max / STEP_DEG) + 1, n_phi=n_phi, d_theta=STEP_DEG, d_phi=STEP_DEG
    )


@dataclass
class PatternSummary:
    max_gain_db: float
    max_theta: float  # degrés depuis le zénith
    max_phi: float  # azimut du maximum, degrés depuis +X
    takeoff_deg: float  # élévation du maximum (90° − θ)
    # Rapport avant/arrière (dB) à l'élévation du maximum ; None si l'arrière est nul
    front_to_back_db: float | None
    # Coupe en azimut à l'élévation du maximum : (azimut °, gain dBi), azimut croissant
    azimuth_cut: list[tuple[float, float]]
    # Coupe verticale dans la direction du maximum : (angle °, gain dBi). L'angle part de
    # l'horizon avant (0°), passe par le zénith (90°) et rejoint l'horizon arrière (180°) ;
    # en espace libre il continue sous l'horizon (-90° à 270°).
    elevation_cut: list[tuple[float, float]]


def _same(a: float, b: float) -> bool:
    return abs(a - b) < 1e-6


def _norm_phi(phi: float) -> float:
    return phi % 360.0


def analyze_pattern(points: list[PatternPoint]) -> PatternSummary | None:
    """Résumé d'un diagramme (grille θ × φ). None si aucun point n'a de gain."""
    valid = [p for p in points if p.gain_total_db > NO_GAIN_DB]
    if not valid:
        return None
    # Plusieurs directions peuvent avoir le même gain max (dipôle en espace libre : tout le plan
    # perpendiculaire au fil). On prend la plus proche de l'horizon, puis le plus petit azimut :
    # sinon on tomberait sur le zénith, avec une coupe en azimut plate et sans intérêt.
    g_max = max(p.gain_total_db for p in valid)
    best = min(
        (p for p in valid if p.gain_total_db >= g_max - 1e-9),
        key=lambda p: (abs(90.0 - p.theta), _norm_phi(p.phi)),
    )
    phi_back = _norm_phi(best.phi + 180.0)

    azimuth_cut = sorted(
        (_norm_phi(p.phi), p.gain_total_db) for p in points if _same(p.theta, best.theta)
    )

    front = [p for p in points if _same(_norm_phi(p.phi), _norm_phi(best.phi))]
    back = [p for p in points if _same(_norm_phi(p.phi), phi_back)]
    elevation_cut = sorted(
        [(90.0 - p.theta, p.gain_total_db) for p in front]
        + [(90.0 + p.theta, p.gain_total_db) for p in back]
    )

    back_gain = next((g for phi, g in azimuth_cut if _same(phi, phi_back) and g > NO_GAIN_DB), None)
    return PatternSummary(
        max_gain_db=best.gain_total_db,
        max_theta=best.theta,
        max_phi=_norm_phi(best.phi),
        takeoff_deg=90.0 - best.theta,
        front_to_back_db=None if back_gain is None else best.gain_total_db - back_gain,
        azimuth_cut=azimuth_cut,
        elevation_cut=elevation_cut,
    )


def simulate_pattern(
    model: AntennaModel, frequency_mhz: float, timeout: float = 120.0
) -> tuple[FrequencyResult, PatternSummary | None]:
    """Simule le modèle à une seule fréquence avec la grille standard, puis l'analyse."""
    single = replace(
        model,
        sweep=FrequencySweep(start_mhz=frequency_mhz),
        pattern=pattern_grid(model.ground),
    )
    fr = simulate(single, timeout=timeout).frequencies[0]
    return fr, analyze_pattern(fr.pattern)
