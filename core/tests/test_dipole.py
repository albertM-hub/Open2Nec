"""Tests du socle : génération du deck, parseur (sortie réelle) et simulation de bout en bout."""

import importlib
from pathlib import Path

import pytest

from open2nec import (
    AntennaModel,
    Excitation,
    FrequencySweep,
    Ground,
    RadiationGrid,
    Wire,
    simulate,
)
from open2nec.engine import EngineError, ModelRejected, find_onec
from open2nec.results import FeedpointResult, FrequencyResult, SimulationResult, parse_output
from open2nec.sweep import resonance, swr_curve
from open2nec.validate import check_excitations, check_segmentation

DATA = Path(__file__).parent / "data"


def dipole(length: float = 10.0, segments: int = 21) -> AntennaModel:
    """Dipôle horizontal en espace libre, alimenté au centre."""
    half = length / 2
    return AntennaModel(
        wires=[Wire(1, segments, (0, -half, 0), (0, half, 0), 0.001)],
        excitations=[Excitation(tag=1, segment=segments // 2 + 1)],
        sweep=FrequencySweep(start_mhz=13.0, step_mhz=0.5, count=5),
        pattern=RadiationGrid(n_theta=7, n_phi=5, d_theta=30, d_phi=90),
    )


def test_deck_generation():
    deck = dipole().to_deck()
    assert "GW 1 21 0 -5 0 0 5 0 0.001" in deck
    assert "EX 0 1 11 0 1 0" in deck
    assert deck.rstrip().endswith("EN")


def test_deck_always_has_execution_card():
    """Sans RP ni XQ, NEC-2 ne calcule rien (régression : résultats vides)."""
    m = dipole()
    assert "RP " in m.to_deck()
    m.pattern = None
    assert "XQ 0" in m.to_deck()


def test_parser_on_real_output():
    """Le parseur doit lire une vraie sortie de onec (3 fréquences, 1 point d'alimentation)."""
    res = parse_output((DATA / "dipole_freespace.out").read_text())
    assert [round(f.frequency_mhz, 1) for f in res.frequencies] == [13.0, 14.0, 15.0]
    for fr in res.frequencies:
        assert len(fr.feedpoints) == 1
        assert fr.pattern, "diagramme vide"
    # La réactance augmente avec la fréquence pour un dipôle autour de la résonance
    xs = [f.feedpoints[0].impedance.imag for f in res.frequencies]
    assert xs == sorted(xs)


def test_segmentation_warning():
    m = dipole(segments=3)  # segments de 3,3 m à 14 MHz : trop longs (> λ/10)
    assert check_segmentation(m)
    assert not check_segmentation(dipole())


def _onec_available() -> bool:
    try:
        find_onec()
        return True
    except EngineError:
        return False


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_dipole_end_to_end():
    """Dipôle demi-onde en espace libre : R ≈ 73 Ω à la résonance, gain ≈ 2,15 dBi."""
    res = simulate(dipole())
    f_res = resonance(res)
    assert f_res is not None and 13.0 < f_res < 15.0

    # impédance au plus près de la résonance
    best = min(res.frequencies, key=lambda f: abs(f.feedpoints[0].impedance.imag))
    r = best.feedpoints[0].impedance.real
    assert 60 < r < 80

    gmax = best.max_gain_db
    assert gmax is not None and 1.9 < gmax < 2.4

    curve = swr_curve(res)
    assert len(curve) == 5 and all(s >= 1.0 for _, s in curve)


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_simulation_without_pattern():
    """Balayage sans diagramme (cas du front) : impédances présentes, diagramme vide."""
    m = dipole()
    m.pattern = None
    res = simulate(m)
    assert len(res.frequencies) == 5
    assert all(len(f.feedpoints) == 1 and not f.pattern for f in res.frequencies)


def test_deck_keeps_precision():
    """Les cartes gardent assez de chiffres (régression : « :g » arrondissait à 6)."""
    m = dipole()
    m.sweep = FrequencySweep(start_mhz=432.1745, step_mhz=0.0125, count=3)
    m.wires[0] = Wire(1, 21, (0, -1234.5678, 0), (0, 1234.5678, 0), 0.001)
    deck = m.to_deck()
    assert "FR 0 3 0 0 432.1745 0.0125" in deck
    assert "-1234.5678" in deck


def _result(reactances: list[float], start: float = 13.0) -> SimulationResult:
    return SimulationResult(
        frequencies=[
            FrequencyResult(start + i, [FeedpointResult(1, 11, complex(70, x))])
            for i, x in enumerate(reactances)
        ]
    )


def test_resonance_interpolation():
    assert resonance(_result([-20, 20])) == pytest.approx(13.5)
    assert resonance(_result([-20, 0, 30])) == 14.0
    assert resonance(_result([-30, -10, 0])) == 15.0  # zéro exact sur le dernier point
    assert resonance(_result([10, 20])) is None
    assert resonance(SimulationResult()) is None


def test_simulate_deck_rejects_empty_output(monkeypatch):
    """Si onec refuse le modèle, on lève une erreur explicite au lieu d'un résultat vide."""
    sim = importlib.import_module("open2nec.simulate")  # « open2nec.simulate » = la fonction

    monkeypatch.setattr(sim, "run_onec", lambda deck, timeout: "\n GEOMETRY DATA ERROR\n")
    with pytest.raises(ModelRejected, match="GEOMETRY DATA ERROR"):
        sim.simulate_deck("CM\nCE\nEN\n")


def test_cli_missing_file(tmp_path, capsys):
    from open2nec.cli import main

    assert main(["run", str(tmp_path / "absent.nec")]) == 1
    assert "lecture" in capsys.readouterr().err


def test_excitation_checks():
    """Excitation sur un fil ou un segment inexistant : erreur bloquante."""
    assert check_excitations(dipole()) == []
    m = dipole()
    m.excitations = [Excitation(tag=2, segment=1)]
    assert "n'existe pas" in check_excitations(m)[0]
    m.excitations = [Excitation(tag=1, segment=22)]  # le fil a 21 segments
    assert "hors limites (1 à 21)" in check_excitations(m)[0]
    m.excitations = [Excitation(tag=1, segment=0)]
    assert check_excitations(m)
    m.excitations = []
    assert "aucune excitation" in check_excitations(m)[0]


def test_model_rejected_is_engine_error():
    """L'API distingue modèle refusé (422) et moteur indisponible (503)."""
    assert issubclass(ModelRejected, EngineError)


def test_engine_rejection_without_output(monkeypatch, tmp_path):
    """onec explique son refus sur stderr sans écrire de sortie → ModelRejected (API : 422)."""
    import subprocess

    from open2nec import engine

    class Proc:
        returncode = -11  # OpenNEC 2.3.x plante après le message
        stderr = "Card 2: Segment 1 lies in the ground plane"

    monkeypatch.setattr(engine, "find_onec", lambda: "onec")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(ModelRejected, match="ground plane"):
        engine.run_onec("CM\nCE\nEN\n")
    Proc.stderr = ""
    with pytest.raises(EngineError) as exc:
        engine.run_onec("CM\nCE\nEN\n")
    assert not isinstance(exc.value, ModelRejected)


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_real_rejection_is_model_rejected():
    """Sur le vrai onec : fil posé à z = 0 sur sol réel → refus du modèle."""
    m = dipole()
    m.pattern = None
    m.ground = Ground("real")
    with pytest.raises(ModelRejected, match="ground plane"):
        simulate(m)


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_exact_frequencies_kept():
    """onec n'imprime que 5 chiffres : les fréquences demandées doivent être conservées."""
    m = dipole()
    m.pattern = None
    m.sweep = FrequencySweep(start_mhz=14.1745, step_mhz=0.0125, count=3)
    res = simulate(m)
    assert [f.frequency_mhz for f in res.frequencies] == pytest.approx(
        [14.1745, 14.187, 14.1995], abs=1e-9
    )
