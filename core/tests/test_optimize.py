"""Optimiseur (jalon 6) : critères, règles, déroulement (sans onec), références physiques (onec)."""

import math

import pytest
import scipy  # noqa: F401 — SciPy absent : erreur visible, pas 20 tests ignorés

from open2nec import AntennaModel, Excitation, FrequencySweep, Wire, simulate
from open2nec import optimize as opt
from open2nec.engine import EngineError, find_onec
from open2nec.model import Symbol
from open2nec.optimize import (
    PENALTY,
    Criteria,
    Objective,
    Trial,
    Variable,
    check_setup,
    mismatch_loss_db,
    optimize,
    score_of,
)


def _onec_available() -> bool:
    try:
        find_onec()
        return True
    except EngineError:
        return False


needs_onec = pytest.mark.skipif(not _onec_available(), reason="onec absent")
C = 299.792458


def dipole(L="9") -> AntennaModel:
    return AntennaModel(
        symbols=[Symbol("L", L), Symbol("h", "0")],
        wires=[Wire(1, 21, (0, "-L/2", "h"), (0, "L/2", "h"), 0.001)],
        excitations=[Excitation(1, 11)],
    )


# --- Critères et règles ---------------------------------------------------------------------


def test_mismatch_loss():
    assert mismatch_loss_db(1.0) == 0.0
    assert mismatch_loss_db(2.0) == pytest.approx(0.512, abs=1e-3)
    assert mismatch_loss_db(3.0) == pytest.approx(1.249, abs=1e-3)
    assert mismatch_loss_db(math.inf) == opt.MAX_SWR_LOSS_DB


def test_score_weights_and_fb_cap():
    c = Criteria(2.0, 0.5, gain_db=7.0, fb_db=45.0)
    obj = Objective(14, 14, w_swr=50, w_gain=25, w_fb=25, direction=(90, 0))
    # AV/AR plafonné à 30 dB : un zéro de 45 dB ne rapporte rien de plus
    assert score_of(c, obj) == pytest.approx((50 * 0.5 - 25 * 7 - 25 * 30) / 100)


def test_band_frequencies():
    assert Objective(14.0, 14.35, 3).frequencies.frequencies == [14.0, 14.175, 14.35]
    assert Objective(14.0, 14.4, 1).frequencies.frequencies == [14.2]


@pytest.mark.parametrize(
    ("variables", "obj", "text"),
    [
        ([], Objective(14, 14), "aucune variable"),
        ([Variable("x", 1, 2)], Objective(14, 14), "n'existe pas"),
        ([Variable("L", 8, 10), Variable("l", 8, 10)], Objective(14, 14), "deux fois"),
        ([Variable("L", 10, 8)], Objective(14, 14), "bornes"),
        ([Variable("L", 9.5, 10)], Objective(14, 14), "hors des bornes"),
        ([Variable("L", 8, 10)], Objective(14, 14, w_swr=0), "poids"),
        ([Variable("L", 8, 10)], Objective(14, 14, w_gain=10), "direction"),
        ([Variable("L", 8, 10)], Objective(14.5, 14), "bande"),
    ],
)
def test_check_setup(variables, obj, text):
    with pytest.raises(ValueError, match=text):
        check_setup(dipole(), variables, obj)


def test_only_number_symbols_can_vary():
    with pytest.raises(ValueError, match="vaut un nombre"):
        check_setup(dipole(L="142.5/14.2"), [Variable("L", 8, 12)], Objective(14, 14))


# --- Déroulement, sur une fonction de score connue (sans onec) --------------------------------


@pytest.fixture
def fake(monkeypatch):
    """Remplace le calcul : score = (L − 10.3)² + (h − 2)² ; L > 11.5 « refusé »."""
    calls: list[dict[str, float]] = []

    def evaluate(model, values, objective, n):
        L = values.get("L", 9.0)
        h = values.get("h", 0.0)
        calls.append(dict(values))
        if L > 11.5:
            return Trial(n, values, PENALTY, error="fils croisés")
        return Trial(n, values, (L - 10.3) ** 2 + (h - 2) ** 2, criteria=Criteria(1, 0))

    monkeypatch.setattr(opt, "evaluate", evaluate)
    return calls


def test_finds_known_minimum_within_bounds(fake):
    progress: list[tuple[Trial, Trial]] = []
    r = optimize(
        dipole(),
        [Variable("L", 8, 12), Variable("h", 0, 5)],
        Objective(14, 14),
        on_progress=lambda t, b: progress.append((t, b)),
    )
    assert r.reason == "converged"
    assert r.best.values["L"] == pytest.approx(10.3, abs=1e-3)
    assert r.best.values["h"] == pytest.approx(2.0, abs=1e-3)
    assert r.start.n == 0 and r.start.values == {"L": 9.0, "h": 0.0}
    assert len(progress) == r.evaluations == len(fake)
    assert all(8 <= c["L"] <= 12 and 0 <= c["h"] <= 5 for c in fake)
    # le « meilleur » transmis ne se dégrade jamais
    bests = [b.score for _, b in progress]
    assert bests == sorted(bests, reverse=True)


def test_rejected_trials_do_not_stop_the_search(fake):
    # départ à 11.4 : le premier pas du simplexe (+10 % de la plage) tombe à 11.8, refusé
    r = optimize(dipole(L="11.4"), [Variable("L", 8, 12)], Objective(14, 14), keep_trials=True)
    assert r.trials[1].error == "fils croisés"
    assert r.best.error is None and r.best.values["L"] == pytest.approx(10.3, abs=1e-3)


def test_max_evaluations_and_stop(fake):
    r = optimize(dipole(), [Variable("L", 8, 12), Variable("h", 0, 5)], Objective(14, 14), 7)
    assert (r.reason, r.evaluations) == ("max_evaluations", 7)
    n = {"calls": 0}

    def stop() -> bool:
        n["calls"] += 1
        return n["calls"] > 4

    r = optimize(dipole(), [Variable("L", 8, 12)], Objective(14, 14), should_stop=stop)
    assert (r.reason, r.evaluations) == ("stopped", 4)
    assert r.best.score <= r.start.score
    # arrêt demandé avant même le départ : l'essai de départ est quand même calculé
    r = optimize(dipole(), [Variable("L", 8, 12)], Objective(14, 14), should_stop=lambda: True)
    assert (r.reason, r.evaluations, r.best) == ("stopped", 1, r.start)


def test_model_is_not_modified(fake):
    m = dipole()
    optimize(m, [Variable("L", 8, 12)], Objective(14, 14))
    assert m.symbols[0].formula == "9"


# --- Références physiques (vrai onec) ---------------------------------------------------------


@needs_onec
def test_dipole_finds_resonance():
    """ROS seul sur 72 Ω, à 14,2 MHz en espace libre : la recherche trouve la résonance.
    Fil de 1 mm (λ/d ≈ 10 000) : raccourcissement d'environ 3 %, L ≈ 0,485 λ."""
    r = optimize(dipole(), [Variable("L", 8, 12)], Objective(14.2, 14.2, 1, z0=72))
    assert r.reason == "converged" and r.evaluations < 60
    L = r.best.values["L"]
    assert 0.48 < L / (C / 14.2) < 0.49
    m = AntennaModel(
        wires=[Wire(1, 21, (0, -L / 2, 0), (0, L / 2, 0), 0.001)],
        excitations=[Excitation(1, 11)],
        sweep=FrequencySweep(14.2),
    )
    z = simulate(m).frequencies[0].feedpoints[0].impedance
    assert abs(z.imag) < 2 and r.best.criteria.swr_max < 1.05


@needs_onec
def test_two_element_yagi_front_to_back():
    """Yagi 2 éléments, réflecteur (longueur, espacement) réglé pour l'AV/AR sur 14,0–14,35."""
    m = AntennaModel(
        symbols=[Symbol("Ld", "10.0"), Symbol("Lr", "10.0"), Symbol("sp", "2.5")],
        wires=[
            Wire(1, 21, ("-sp", "-Lr/2", 0), ("-sp", "Lr/2", 0), 0.001),
            Wire(2, 21, (0, "-Ld/2", 0), (0, "Ld/2", 0), 0.001),
        ],
        excitations=[Excitation(2, 11)],
    )
    variables = [Variable("Lr", 9.5, 11.5), Variable("sp", 1.5, 5)]
    obj = Objective(14.0, 14.35, 3, direction=(90, 0), w_swr=0, w_fb=100)
    r = optimize(m, variables, obj)
    start, best = r.start.criteria, r.best.criteria
    assert best.fb_db > start.fb_db + 15 and best.fb_db > 8
    assert best.gain_db > 5.5  # Yagi 2 éléments en espace libre : 6 à 7 dBi
    assert r.best.values["Lr"] > 10.0  # réflecteur plus long que le radiateur
    assert all(v.low <= r.best.values[v.name] <= v.high for v in variables)


@needs_onec
def test_rejected_geometry_is_penalised():
    """h < 0 sur sol parfait : refusé par le contrôle du modèle, pénalisé, sans arrêt."""
    m = dipole(L="10")
    m.symbols[1] = Symbol("h", "1")
    m.ground.kind = "perfect"
    r = opt.evaluate(m, {"h": -1.0}, Objective(14.2, 14.2, 1), 1)
    assert r.score == PENALTY and r.error


def test_direction_without_radiation_is_refused(monkeypatch):
    """θ = 90° au-dessus du sol : pas de gain au départ → refus clair, pas 300 essais inutiles."""

    def evaluate(model, values, objective, n):
        return Trial(n, values, PENALTY / 2, criteria=Criteria(1.5, 0.18, gain_db=None))

    monkeypatch.setattr(opt, "evaluate", evaluate)
    obj = Objective(14, 14, direction=(90, 0), w_swr=50, w_gain=50)
    with pytest.raises(ValueError, match="aucun rayonnement dans la direction θ = 90°"):
        optimize(dipole(), [Variable("L", 8, 12)], obj)
