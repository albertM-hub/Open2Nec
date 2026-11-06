"""Modèles pré-remplis écrits avec des symboles (jalon 7) : Yagi 3 éléments, quad 2 éléments."""

import pytest

from open2nec import AntennaModel, Excitation, Ground, Wire, simulate
from open2nec.engine import EngineError, find_onec
from open2nec.pattern import simulate_pattern
from open2nec.presets import PRESETS, RADIUS, quad2, yagi3
from open2nec.symbols import resolve


def _onec_available() -> bool:
    try:
        find_onec()
        return True
    except EngineError:
        return False


needs_onec = pytest.mark.skipif(not _onec_available(), reason="onec absent")


def yagi3_numbers() -> AntennaModel:
    """La Yagi d'avant le jalon 7, en nombres (référence)."""
    elements = [(0.0, 10.66), (4.22, 10.28), (7.39, 9.71)]
    return AntennaModel(
        wires=[
            Wire(tag, 21, (x, -length / 2, 12.0), (x, length / 2, 12.0), RADIUS)
            for tag, (x, length) in enumerate(elements, start=1)
        ],
        excitations=[Excitation(2, 11)],
        ground=Ground("real"),
    )


def test_preset_ids_and_z0():
    assert [p.id for p in PRESETS] == ["dipole", "ground_plane", "yagi3", "inverted_v", "quad2"]
    assert next(p for p in PRESETS if p.id == "quad2").z0 == 120.0
    assert all(p.z0 == 50.0 for p in PRESETS if p.id != "quad2")


def test_symbol_presets_offer_number_variables():
    """Les symboles qui valent un nombre sont ceux que l'optimiseur peut faire varier."""
    assert [s.name for s in yagi3().symbols] == ["h", "Lr", "Ld", "Ldir", "xd", "xdir"]
    assert [s.name for s in quad2().symbols if s.formula.replace(".", "").isdigit()] == ["f", "h"]


@needs_onec
def test_yagi_symbols_same_geometry_and_results():
    res = resolve(yagi3())
    ref = yagi3_numbers()
    for w, r in zip(res.model.wires, ref.wires, strict=True):
        assert w.start == pytest.approx(r.start, abs=1e-5)
        assert w.end == pytest.approx(r.end, abs=1e-5)
    za = simulate(yagi3()).frequencies[6].feedpoints[0].impedance  # 14,2 MHz
    ref.sweep = yagi3().sweep
    zb = simulate(ref).frequencies[6].feedpoints[0].impedance
    assert abs(za - zb) < 0.01


@needs_onec
def test_quad_resonant_with_typical_figures():
    """Quad 2 éléments : X ≈ 0 à 14,2 MHz, Z ≈ 120 Ω ; 7 à 8 dBi et AV/AR > 15 dB en espace
    libre ; lobe vers +X, départ vers 22° à 12 m sur sol réel."""
    m = quad2()
    res = resolve(m)
    assert res.issues == [] and len(res.model.wires) == 8
    assert res.values["ad"] == pytest.approx(5.326, abs=1e-3)  # 1.0092 × λ/4
    fr, s = simulate_pattern(m, 14.2)
    z = fr.feedpoints[0].impedance
    assert abs(z.imag) < 2 and 110 < z.real < 135
    assert abs(s.max_phi) < 1 and 18 < s.takeoff_deg < 26
    m.ground = Ground("free")
    _, s = simulate_pattern(m, 14.2)
    assert 7.0 < s.max_gain_db < 8.0 and s.front_to_back_db > 15
