"""Analyse d'un balayage (jalon 3) : ROS pour un Z0, résonances, bandes, gain avant/arrière."""

import math

import pytest

from open2nec.engine import EngineError, find_onec
from open2nec.model import FrequencySweep
from open2nec.pattern import simulate_pattern
from open2nec.presets import PRESETS
from open2nec.results import FeedpointResult, FrequencyResult, PatternPoint, SimulationResult
from open2nec.sweep import analyze_sweep, find_band, reflection, resonances, simulate_sweep


def _onec_available() -> bool:
    try:
        find_onec()
        return True
    except EngineError:
        return False


needs_onec = pytest.mark.skipif(not _onec_available(), reason="onec absent")


def _result(impedances: list[complex], start: float = 14.0, step: float = 0.1) -> SimulationResult:
    return SimulationResult(
        frequencies=[
            FrequencyResult(round(start + i * step, 9), [FeedpointResult(1, 1, z)])
            for i, z in enumerate(impedances)
        ]
    )


# --- Sans onec -------------------------------------------------------------------------------


def test_reflection_and_swr_depend_on_z0():
    z = complex(75, 0)
    assert reflection(z, 75.0) == 0
    pts50, _ = analyze_sweep(_result([z]), z0=50)
    pts75, s75 = analyze_sweep(_result([z]), z0=75)
    assert pts50[0].swr == pytest.approx(1.5) and pts75[0].swr == pytest.approx(1.0)
    assert s75.z0 == 75 and s75.min_swr == pytest.approx(1.0)
    with pytest.raises(ValueError):
        analyze_sweep(_result([z]), z0=0)


def test_band_edges_are_interpolated():
    # ROS 3, 1.5, 1, 1.5, 3 sur 14,0 → 14,4 MHz : seuil 2 franchi au tiers de chaque intervalle
    freqs = [14.0, 14.1, 14.2, 14.3, 14.4]
    band = find_band(freqs, [3.0, 1.5, 1.0, 1.5, 3.0], 2.0)
    assert band.low_mhz == pytest.approx(14.1 - 0.1 / 3)
    assert band.high_mhz == pytest.approx(14.3 + 0.1 / 3)
    assert band.width_khz == pytest.approx(266.667, abs=0.01)
    assert not band.low_open and not band.high_open


def test_band_open_at_sweep_edge_and_unreached():
    freqs = [14.0, 14.1, 14.2]
    band = find_band(freqs, [1.2, 1.6, 3.0], 2.0)
    assert band.low_open and band.low_mhz == 14.0 and not band.high_open
    assert find_band(freqs, [2.5, 2.2, 3.0], 2.0) is None
    assert find_band(freqs, [1.2, math.inf, 3.0], 1.5).high_mhz < 14.1  # ROS infini toléré


def test_several_resonances():
    # réactance : −20, +20, −10 → deux passages par zéro
    found = resonances(_result([complex(50, -20), complex(50, 20), complex(50, -10)]))
    assert found == pytest.approx([14.05, 14.1 + 0.1 * 20 / 30])


def test_front_back_from_reduced_pattern():
    fr = FrequencyResult(
        14.2,
        [FeedpointResult(1, 1, complex(50, 0))],
        [PatternPoint(60, 270, 10.0), PatternPoint(60, 450, -5.0)],  # φ + 180 imprimé « 450 »
    )
    (pt,), _ = analyze_sweep(SimulationResult([fr]), direction_phi=270)
    assert (pt.gain_db, pt.gain_back_db, pt.front_to_back_db) == (10.0, -5.0, 15.0)
    fr.pattern[1] = PatternPoint(60, 450, -999.99)  # arrière nul : AV/AR non défini
    (pt,), _ = analyze_sweep(SimulationResult([fr]), direction_phi=270)
    assert pt.gain_back_db is None and pt.front_to_back_db is None


def test_sweep_frequencies_have_no_float_noise():
    assert FrequencySweep(13.9, 0.05, 13).frequencies[6] == 14.2


# --- Avec onec -------------------------------------------------------------------------------


@needs_onec
def test_sweep_gain_matches_full_pattern():
    """Gain et AV/AR du balayage réduit (2 directions) = ceux du diagramme complet."""
    m = next(p for p in PRESETS if p.id == "yagi3").build()
    _, s = simulate_pattern(m, 14.2)
    _, points, summary = simulate_sweep(m, 50, (s.max_theta, s.max_phi))
    at = next(p for p in points if p.frequency_mhz == 14.2)
    assert at.gain_db == pytest.approx(s.max_gain_db, abs=0.1)
    assert at.front_to_back_db == pytest.approx(s.front_to_back_db, abs=0.1)
    assert len(points) == m.sweep.count and all(p.gain_db is not None for p in points)
    assert summary.resonances and 14.0 < summary.resonances[0] < 14.4


@needs_onec
def test_dipole_bandwidth_is_plausible():
    """Dipôle 20 m à 10 m : bande à ROS 2 de plusieurs centaines de kHz, centrée sur 14,2."""
    m = next(p for p in PRESETS if p.id == "dipole").build()
    m.sweep = FrequencySweep(13.5, 0.05, 31)
    *_, summary = simulate_sweep(m)
    band2 = next(b for b in summary.bands if b.threshold == 2.0)
    assert 300 < band2.width_khz < 1200 and band2.low_mhz < 14.2 < band2.high_mhz
    assert not band2.low_open and not band2.high_open
    assert summary.min_swr < 1.5
