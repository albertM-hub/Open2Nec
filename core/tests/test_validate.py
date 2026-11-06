"""Contrôle du modèle (jalon 5) : chaque règle déclenchée par un cas minimal, et pas par sa
version corrigée. Aucun appel à onec."""

import pytest

from open2nec import AntennaModel, Excitation, FrequencySweep, Ground, Wire
from open2nec.engine import EngineError, find_onec
from open2nec.presets import PRESETS
from open2nec.symbols import resolve
from open2nec.validate import MAX_PAIRWISE_WIRES, validate_model

F = 14.2  # λ ≈ 21,1 m
R = 0.001


def model(*wires: Wire, feed=(1, 11), ground="free", exact=True, extra=()) -> AntennaModel:
    return AntennaModel(
        wires=list(wires),
        excitations=[Excitation(*feed)],
        ground=Ground(ground, exact=exact),
        sweep=FrequencySweep(F),
        extra_cards=list(extra),
    )


def dipole(tag=1, x=0.0, z=10.0, segs=21, half=5.0, radius=R) -> Wire:
    return Wire(tag, segs, (x, -half, z), (x, half, z), radius)


def codes(m: AntennaModel) -> dict[str, str]:
    return {i.code: i.severity for i in validate_model(m)}


def test_clean_dipole_has_no_remark():
    assert validate_model(model(dipole())) == []


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_presets_have_no_remark(preset):
    m = preset.build()
    if m.has_formulas:  # Yagi, quad : formules calculées par onec
        try:
            find_onec()
        except EngineError:
            pytest.skip("onec absent")
        m = resolve(m).model
    assert validate_model(m, 14.5) == []


# --- Erreurs ---------------------------------------------------------------------------------


def test_ground_flat_and_below():
    flat = model(dipole(z=0), ground="real")
    assert codes(flat) == {"ground_flat": "error"}
    assert validate_model(flat)[0].wires == (0,)
    assert "ground_below" in codes(model(Wire(1, 21, (0, -5, -1), (0, 5, 1), R), ground="perfect"))
    assert codes(model(dipole(z=0))) == {}  # espace libre : pas de sol
    # verticale posée par une extrémité : valable (fil relié au sol)
    vertical = model(Wire(1, 11, (0, 0, 0), (0, 0, 5), R), feed=(1, 1), ground="perfect")
    assert codes(vertical) == {}


def test_ground_approx_advice():
    low = model(dipole(z=1), ground="real", exact=False)
    assert codes(low) == {"ground_approx": "info"}
    assert codes(model(dipole(z=1), ground="real", exact=True)) == {}
    assert codes(model(dipole(z=10), ground="real", exact=False)) == {}  # à ~0,5 λ


def test_overlapping_wires():
    assert codes(model(dipole(), dipole(tag=2))) == {"overlap": "error"}
    reversed_ = Wire(2, 21, (0, 5, 10), (0, -5, 10), R)
    assert codes(model(dipole(), reversed_))["overlap"] == "error"


def test_excitation_and_kept_cards():
    assert codes(model(dipole(), feed=(9, 1)))["excitation"] == "error"
    bad = model(dipole(), extra=["LD 0 5 3 3 50"])
    issue = next(i for i in validate_model(bad) if i.code == "extra_card")
    assert issue.severity == "error" and "tag 5" in issue.message
    assert "extra_card" in codes(model(dipole(), extra=["LD 0 1 30 30 50"]))  # segment 30 > 21
    ok = ["LD 5 0 0 0 5.8e7", "LD 0 1 3 3 50", "LD 0 0 4 4 10", "TL 1 3 1 19 450"]
    assert codes(model(dipole(), extra=ok)) == {}


# --- Avertissements --------------------------------------------------------------------------


def test_segment_length_vs_wavelength():
    assert codes(model(dipole(segs=3)))["segment_long"] == "warning"  # 3,3 m > λ/10
    assert codes(model(dipole(segs=2001, half=5)))["segment_short"] == "warning"


def test_thin_wire_tiers():
    assert codes(model(dipole(segs=21, radius=0.3)))["thin_wire"] == "warning"  # 0,48 / 0,3 < 2
    assert codes(model(dipole(segs=21, radius=0.1)))["thin_wire_marginal"] == "info"  # ≈ 4,8


def test_wire_ending_mid_segment_is_not_connected():
    # verticale qui part du milieu du fil : sur 21 segments, y = 0 tombe au milieu du segment 11
    stub = Wire(2, 5, (0, 0, 10), (0, 0, 12), R)
    issue = next(i for i in validate_model(model(dipole(), stub)) if i.code == "mid_segment")
    assert (
        issue.severity == "warning" and issue.wires == (0, 1) and "PAS connectés" in issue.message
    )
    # 20 segments : y = 0 est une limite de segment → vraie jonction
    assert "mid_segment" not in codes(model(dipole(segs=20), stub, feed=(1, 10)))


def test_junction_segments_and_radius():
    left = Wire(1, 41, (0, -5, 10), (0, 0, 10), R)
    right = Wire(2, 3, (0, 0, 10), (0, 5, 10), R)
    assert codes(model(left, right, feed=(1, 20)))["junction_segments"] == "warning"
    thick = Wire(2, 41, (0, 0, 10), (0, 5, 10), 0.01)
    assert codes(model(left, thick, feed=(1, 20)))["junction_radius"] == "warning"
    even = Wire(2, 41, (0, 0, 10), (0, 5, 10), R)
    assert codes(model(left, even, feed=(1, 20))) == {}


def test_feed_on_free_wire_end():
    assert codes(model(dipole(), feed=(1, 1)))["feed_free_end"] == "warning"
    assert codes(model(dipole(), feed=(1, 21)))["feed_free_end"] == "warning"
    # base d'un ground plane : segment 1, mais à la jonction avec les radians → valable
    gp = next(p for p in PRESETS if p.id == "ground_plane").build()
    assert "feed_free_end" not in {i.code for i in validate_model(gp)}


def test_parallel_close_wires_alignment():
    a = dipole(segs=21)
    misaligned = dipole(tag=2, x=0.05, segs=15)  # à 5 cm, segmentation différente
    issue = next(i for i in validate_model(model(a, misaligned)) if i.code == "parallel_misaligned")
    assert issue.severity == "warning"
    assert "parallel_misaligned" not in codes(model(a, dipole(tag=2, x=0.05, segs=21)))
    assert codes(model(a, dipole(tag=2, x=4.0, segs=15))) == {}  # éléments de Yagi : loin


def test_crossing_wires():
    # croix au milieu de segments (21 segments chacun : centre = milieu du segment 11)
    cross = Wire(2, 21, (-5, 0, 10), (5, 0, 10), R)
    assert codes(model(dipole(), cross))["crossing"] == "warning"
    # croix sur des limites de segments (20 segments chacun) : jonction NEC, pas d'avertissement
    cross20 = Wire(2, 20, (-5, 0, 10), (5, 0, 10), R)
    assert "crossing" not in codes(model(dipole(segs=20), cross20, feed=(1, 10)))


# --- Conseils, regroupement, ordre ---------------------------------------------------------


def test_feed_advice():
    assert codes(model(dipole(segs=20), feed=(1, 10)))["feed_even"] == "info"
    coarse = model(dipole(segs=7, half=5), feed=(1, 4))  # segment de 1,43 m ≈ 0,068 λ
    assert codes(coarse)["feed_coarse"] == "info"


def test_identical_remarks_are_grouped():
    thin = [dipole(tag=t, x=3.0 * t, radius=0.3) for t in range(1, 6)]
    issues = [i for i in validate_model(model(*thin)) if i.code == "thin_wire"]
    assert len(issues) == 1 and issues[0].wires == (0, 1, 2, 3, 4)
    assert "4 autres cas" in issues[0].message


def test_errors_come_first_and_pairwise_limit():
    m = model(dipole(z=0), dipole(tag=2, segs=3, x=4), ground="real")
    severities = [i.severity for i in validate_model(m)]
    assert severities == sorted(severities, key=["error", "warning", "info"].index)
    many = [Wire(t, 1, (0.1 * t, 0, 10), (0.1 * t, 0.5, 10), R) for t in range(1, 502)]
    assert "pairs_skipped" in codes(model(*many, feed=(1, 1)))
    assert MAX_PAIRWISE_WIRES == 500
