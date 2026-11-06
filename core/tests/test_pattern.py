"""Diagramme de rayonnement (analyse, coupes) et modèles pré-remplis."""

import pytest

from open2nec import AntennaModel, Excitation, Ground, Wire
from open2nec.engine import EngineError, find_onec
from open2nec.pattern import analyze_pattern, pattern_grid, simulate_pattern
from open2nec.presets import PRESETS
from open2nec.results import PatternPoint
from open2nec.symbols import resolve
from open2nec.validate import check_excitations, check_segmentation

LAMBDA_14_2 = 299.792458 / 14.2


def _onec_available() -> bool:
    try:
        find_onec()
        return True
    except EngineError:
        return False


needs_onec = pytest.mark.skipif(not _onec_available(), reason="onec absent")


# --- Sans onec : grille et analyse sur des points construits à la main --------------------


def test_grid_hemisphere_with_ground():
    g = pattern_grid(Ground("real"))
    assert (g.n_theta, g.n_phi, g.d_theta, g.d_phi) == (46, 180, 2.0, 2.0)  # θ 0–90°, φ 0–358°
    assert pattern_grid(Ground("free")).n_theta == 91  # θ 0–180°


def _grid(gain) -> list[PatternPoint]:
    """Grille θ 0–90° × φ 0–270° (pas de 90°/30°) avec gain(θ, φ)."""
    return [
        PatternPoint(theta=t, phi=p, gain_total_db=gain(t, p))
        for p in (0.0, 90.0, 180.0, 270.0)
        for t in (0.0, 30.0, 60.0, 90.0)
    ]


def test_analyze_directional():
    # Lobe vers φ = 90°, élévation 30° (θ = 60°) ; arrière (φ = 270°) 15 dB plus bas
    def gain(t, p):
        base = {0.0: -5.0, 90.0: 10.0, 180.0: -5.0, 270.0: -5.0}[p]
        return base - abs(t - 60.0) / 10

    s = analyze_pattern(_grid(gain))
    assert (s.max_gain_db, s.max_theta, s.max_phi, s.takeoff_deg) == (10.0, 60.0, 90.0, 30.0)
    assert s.front_to_back_db == pytest.approx(15.0)
    assert [phi for phi, _ in s.azimuth_cut] == [0.0, 90.0, 180.0, 270.0]
    # coupe verticale : avant (0–90°) puis arrière (90–180°), le zénith apparaît des deux côtés
    angles = [a for a, _ in s.elevation_cut]
    assert angles == sorted(angles) and angles[0] == 0.0 and angles[-1] == 180.0
    assert (30.0, 10.0) in s.elevation_cut


def test_analyze_tie_prefers_horizon():
    """Gain identique partout : on retient l'horizon, pas le zénith."""
    s = analyze_pattern(_grid(lambda t, p: 2.0))
    assert s.max_theta == 90.0 and s.takeoff_deg == 0.0 and s.max_phi == 0.0


def test_analyze_no_gain():
    assert analyze_pattern(_grid(lambda t, p: -999.99)) is None
    assert analyze_pattern([]) is None


def test_analyze_back_null():
    """Arrière sans rayonnement : rapport AV/AR non défini plutôt qu'absurde (1000 dB)."""
    s = analyze_pattern(_grid(lambda t, p: -999.99 if p == 180.0 else 5.0))
    assert s.front_to_back_db is None


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_presets_are_valid_models(preset):
    m = preset.build()
    if m.has_formulas:  # Yagi, quad : formules calculées par onec
        if not _onec_available():
            pytest.skip("onec absent")
        m = resolve(m).model
    assert check_excitations(m) == []
    assert check_segmentation(m) == []
    assert all(min(w.start[2], w.end[2]) > 0 for w in m.wires), "fil au niveau du sol"
    assert m.sweep.frequencies[0] < preset.design_mhz < m.sweep.frequencies[-1]


# --- Avec onec : cas de référence physiques ----------------------------------------------


def _dipole(height: float, ground: str) -> AntennaModel:
    half = 0.475 * LAMBDA_14_2 / 2
    return AntennaModel(
        wires=[Wire(1, 21, (0, -half, height), (0, half, height), 0.001)],
        excitations=[Excitation(1, 11)],
        ground=Ground(ground),
    )


@needs_onec
def test_dipole_free_space_pattern():
    """Dipôle selon Y en espace libre : ≈ 2,1 dBi à l'horizon, perpendiculaire au fil, symétrique."""
    fr, s = simulate_pattern(_dipole(0, "free"), 14.2)
    assert len(fr.pattern) == 91 * 180
    assert 1.9 < s.max_gain_db < 2.4
    assert s.takeoff_deg == 0.0 and s.max_phi in (0.0, 180.0)
    assert s.front_to_back_db == pytest.approx(0.0, abs=0.1)
    # nul dans l'axe du fil (φ = 90°)
    g90 = dict(s.azimuth_cut)[90.0]
    assert g90 < s.max_gain_db - 20


@needs_onec
def test_dipole_half_wave_over_perfect_ground_takeoff():
    """Dipôle horizontal à λ/2 au-dessus d'un sol parfait : départ à 30° (sin α = λ / 4h)."""
    _, s = simulate_pattern(_dipole(LAMBDA_14_2 / 2, "perfect"), 14.2)
    assert s.takeoff_deg == pytest.approx(30.0, abs=2.0)
    assert len(s.azimuth_cut) == 180
    assert all(-1.0 <= a <= 181.0 for a, _ in s.elevation_cut)


@needs_onec
@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_presets_resonate(preset):
    """Chaque modèle livré doit être accordé : ROS < 2 à sa fréquence, sur l'impédance de
    référence proposée avec lui (50 Ω, ou 120 Ω pour la quad)."""
    fr, s = simulate_pattern(preset.build(), preset.design_mhz)
    assert fr.feedpoints[0].swr(preset.z0) < 2.0
    assert s is not None and s.max_gain_db > 0


@needs_onec
def test_yagi_is_directional():
    preset = next(p for p in PRESETS if p.id == "yagi3")
    _, s = simulate_pattern(preset.build(), preset.design_mhz)
    assert s.max_phi == 0.0  # lobe vers +X (côté directeur)
    assert s.front_to_back_db is not None and s.front_to_back_db > 10
