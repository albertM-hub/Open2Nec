"""Modèles pré-remplis, accordés sur 14,2 MHz avec onec (sol réel, rayon 1 mm).

Les cotes ont été trouvées par recherche numérique (réactance nulle à 14,2 MHz) ; les tests
vérifient que chaque modèle reste sous ROS 2 à sa fréquence. Aucun fil n'est posé à z = 0 :
onec refuse ce cas (et plante, voir OpenNEC issue #30).

La Yagi et la quad sont écrites avec des symboles (jalon 6) : on peut les optimiser directement.
Leurs formules sont calculées par onec (symbols.resolve) ; les tests vérifient qu'elles donnent
la même géométrie que les cotes d'origine.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from .model import AntennaModel, Excitation, FrequencySweep, Ground, Symbol, Wire

RADIUS = 0.001
DESIGN_MHZ = 14.2


@dataclass
class Preset:
    id: str
    name: str
    description: str
    design_mhz: float
    build: Callable[[], AntennaModel]
    z0: float = 50.0  # impédance de référence du ROS proposée pour ce modèle (Ω)


def _mm(v: float) -> float:
    """Arrondi au millimètre, sans « -0 » dans le deck."""
    return round(v, 3) + 0.0


def _sweep() -> FrequencySweep:
    # 13,9 à 14,5 MHz par pas de 50 kHz : couvre la bande des 20 m
    return FrequencySweep(start_mhz=13.9, step_mhz=0.05, count=13)


def dipole() -> AntennaModel:
    half = 5.16
    return AntennaModel(
        wires=[Wire(1, 21, (0, -half, 10), (0, half, 10), RADIUS)],
        excitations=[Excitation(1, 11)],
        ground=Ground("real"),
        sweep=_sweep(),
        comment="Dipole demi-onde 14.2 MHz a 10 m",
    )


def ground_plane() -> AntennaModel:
    base, length, droop = 5.0, 5.11, math.radians(45)
    wires = [Wire(1, 11, (0, 0, base), (0, 0, base + length), RADIUS)]
    for k in range(4):
        a = math.pi / 2 * k
        end = (
            _mm(length * math.cos(droop) * math.cos(a)),
            _mm(length * math.cos(droop) * math.sin(a)),
            _mm(base - length * math.sin(droop)),
        )
        wires.append(Wire(2 + k, 11, (0, 0, base), end, RADIUS))
    return AntennaModel(
        wires=wires,
        excitations=[Excitation(1, 1)],  # alimentation à la base du brin vertical
        ground=Ground("real"),
        sweep=_sweep(),
        comment="Ground plane quart d'onde 14.2 MHz, 4 radians a 45 deg, base a 5 m",
    )


def yagi3() -> AntennaModel:
    # Boom selon +X : réflecteur, radiateur, directeur ; lobe principal vers +X.
    # Cotes d'origine : réflecteur 10,66 m en x = 0, radiateur 10,28 m en 4,22, directeur 9,71 m
    # en 7,39, à 12 m.
    symbols = [
        Symbol("h", "12"),
        Symbol("Lr", "10.66"),
        Symbol("Ld", "10.28"),
        Symbol("Ldir", "9.71"),
        Symbol("xd", "4.22"),
        Symbol("xdir", "7.39"),
    ]
    elements = [("0", "Lr"), ("xd", "Ld"), ("xdir", "Ldir")]  # (x, longueur)
    wires = [
        Wire(tag, 21, (x, f"-{length}/2", "h"), (x, f"{length}/2", "h"), RADIUS)
        for tag, (x, length) in enumerate(elements, start=1)
    ]
    return AntennaModel(
        wires=wires,
        symbols=symbols,
        excitations=[Excitation(2, 11)],
        ground=Ground("real"),
        sweep=_sweep(),
        comment="Yagi 3 elements 14.2 MHz a 12 m, boom 7.39 m",
    )


def _square(tag: int, x: str, side: str) -> list[Wire]:
    """Boucle carrée dans le plan YZ, centrée à la hauteur h : bas, côté, haut, côté.
    11 segments par côté : le 6e est le milieu du côté bas (alimentation, polarisation H)."""
    lo, hi, left, right = f"h-{side}/2", f"h+{side}/2", f"-{side}/2", f"{side}/2"
    return [
        Wire(tag, 11, (x, left, lo), (x, right, lo), RADIUS),
        Wire(tag + 1, 11, (x, right, lo), (x, right, hi), RADIUS),
        Wire(tag + 2, 11, (x, right, hi), (x, left, hi), RADIUS),
        Wire(tag + 3, 11, (x, left, hi), (x, left, lo), RADIUS),
    ]


def quad2() -> AntennaModel:
    # Radiateur en x = 0, réflecteur derrière (x = -sp) : lobe vers +X. Côtés exprimés en λ/4 :
    # réflecteur 6 % plus grand (1,06), espacement 0,15 λ. Le facteur du radiateur (1,0092) a été
    # trouvé par recherche numérique pour une réactance nulle à 14,2 MHz sur sol réel :
    # Z ≈ 122 Ω, 7,4 dBi et AV/AR ≈ 23 dB en espace libre.
    symbols = [
        Symbol("f", "14.2"),
        Symbol("lam", "299.79/f"),
        Symbol("ad", "1.0092*lam/4"),
        Symbol("ar", "1.06*lam/4"),
        Symbol("sp", "0.15*lam"),
        Symbol("h", "12"),
    ]
    return AntennaModel(
        wires=_square(1, "0", "ad") + _square(5, "-sp", "ar"),
        symbols=symbols,
        excitations=[Excitation(1, 6)],
        ground=Ground("real"),
        sweep=_sweep(),
        comment="Quad 2 elements 14.2 MHz a 12 m",
    )


def inverted_v() -> AntennaModel:
    # Deux brins de 4,925 m à 120° l'un de l'autre, reliés par un fil central d'alimentation
    apex, leg, gap = 12.0, 4.925, 0.5
    slope = math.radians(30)  # brins à 30° sous l'horizontale
    y0 = gap / 2
    y_end, z_end = _mm(y0 + leg * math.cos(slope)), _mm(apex - leg * math.sin(slope))
    return AntennaModel(
        wires=[
            Wire(1, 11, (0, -y_end, z_end), (0, -y0, apex), RADIUS),
            Wire(2, 1, (0, -y0, apex), (0, y0, apex), RADIUS),
            Wire(3, 11, (0, y0, apex), (0, y_end, z_end), RADIUS),
        ],
        excitations=[Excitation(2, 1)],
        ground=Ground("real"),
        sweep=_sweep(),
        comment="V inverse 14.2 MHz, sommet a 12 m, 120 deg",
    )


PRESETS: list[Preset] = [
    Preset("dipole", "Dipôle λ/2", "Dipôle horizontal à 10 m, sol réel", DESIGN_MHZ, dipole),
    Preset(
        "ground_plane",
        "Ground plane λ/4",
        "Brin vertical et 4 radians inclinés à 45°, base à 5 m",
        DESIGN_MHZ,
        ground_plane,
    ),
    Preset(
        "yagi3",
        "Yagi 3 éléments",
        "Boom de 7,4 m à 12 m, lobe vers +X ; cotes en symboles, prêtes pour l'optimiseur",
        DESIGN_MHZ,
        yagi3,
    ),
    Preset("inverted_v", "V inversé", "Sommet à 12 m, brins à 120°", DESIGN_MHZ, inverted_v),
    Preset(
        "quad2",
        "Quad 2 éléments",
        "Boucles carrées à 12 m, espacement 0,15 λ, lobe vers +X ; Z ≈ 122 Ω (ROS mesuré sur "
        "Z0 = 120 Ω)",
        DESIGN_MHZ,
        quad2,
        z0=120.0,
    ),
]
