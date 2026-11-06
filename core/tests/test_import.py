"""Import de fichiers .nec (jalon 4) : lecture de la sortie onec, regroupement, refus, fidélité."""

import itertools
import re
from pathlib import Path

import pytest

from open2nec import AntennaModel, Excitation, Ground, Wire, simulate
from open2nec.cards import Card, describe_card, parse_card
from open2nec.engine import EngineError, find_onec
from open2nec.importer import (
    ImportRefused,
    card_codes,
    import_deck,
    parse_data_cards,
    parse_segments,
    segments_to_wires,
    strip_execution,
)
from open2nec.simulate import simulate_deck
from open2nec.validate import check_excitations

DATA = Path(__file__).parent / "data"
DECK = (DATA / "import_yagi_4nec2.nec").read_text()
# Sortie réelle de onec 2.3.2 pour ce fichier, cartes RP et PT retirées (lecture sans calcul)
OUTPUT = (DATA / "import_yagi_4nec2.out").read_text()


def _onec_available() -> bool:
    try:
        find_onec()
        return True
    except EngineError:
        return False


needs_onec = pytest.mark.skipif(not _onec_available(), reason="onec absent")


# --- Lecture du fichier d'origine (sans onec) -----------------------------------------------


def test_card_codes_skip_comments_and_continuations():
    deck = "CM x\n' commentaire 4NEC2\nGW 1 3 0 0 0\n  lam/2 h 0.001\nEX2,0,1\nrp 0 1 1\n"
    assert [c for _, c in card_codes(deck)] == ["CM", "GW", "EX", "RP"]


def test_strip_execution_keeps_model_cards():
    stripped = strip_execution(DECK)
    codes = [c for _, c in card_codes(stripped)]
    assert "RP" not in codes and "PT" not in codes
    for kept in ("SY f=14.2", "GM 1 1", "LD 1 1 7 7", "FR 0 3"):
        assert kept in stripped


# --- Lecture de la sortie de onec (fixture réelle, sans onec) -------------------------------


def test_parse_segments_real_output():
    segs = parse_segments(OUTPUT)
    assert len(segs) == 21 + 21 + 8  # dipôle, sa copie GM, l'arc GA
    assert [s.tag for s in segs[:1] + segs[21:22] + segs[42:43]] == [1, 2, 5]
    first = segs[0]
    assert first.center == (0.0, -4.85714, 12.0) and first.length == pytest.approx(0.48571)
    assert segs[21].center[0] == 3.5  # copie décalée de sp = 3,5 m


def test_parse_segments_glued_columns():
    """Colonnes pleines collées (%10.5f sans séparateur) : « 84.37500-180.00000 »."""
    out = (
        "  - - - - SEGMENTATION DATA - - - -\n"
        "  SEG.   COORDINATES OF SEG. CENTER     SEG.     ORIENTATION ANGLES    WIRE\n"
        "     1   1.98079   0.00000   0.19509   0.39207   84.37500-180.00000   0.00200"
        "     0    1    2      5\n"
        "\n  DATA CARD No:   1 FR   0     1     0     0  1.42000E+01  0.00000E+00\n"
    )
    (seg,) = parse_segments(out)
    assert (seg.alpha, seg.beta, seg.radius, seg.tag) == (84.375, -180.0, 0.002, 5)


def test_parse_data_cards_evaluated():
    cards = parse_data_cards(OUTPUT)
    assert [c.code for c in cards] == ["GN", "LD", "LD", "EX", "EX", "FR"]
    fr = cards[-1]
    assert fr.ints[1] == 3 and fr.floats[:2] == (14.2, 0.1)  # symbole f évalué
    assert cards[2].floats[1:3] == (4.7e-06, 5.6e-11)


def test_segments_to_wires():
    wires = segments_to_wires(parse_segments(OUTPUT))
    assert [(w.tag, w.segments) for w in wires[:2]] == [(1, 21), (2, 21)]
    assert wires[0].start == (0.0, -5.1, 12.0) and wires[0].end == (0.0, 5.1, 12.0)
    arc = wires[2:]
    assert len(arc) == 8 and all(w.tag == 5 and w.segments == 1 for w in arc)
    # morceaux d'arc exactement jointifs (sinon NEC les croirait déconnectés)
    assert all(a.end == b.start for a, b in itertools.pairwise(arc))
    assert arc[0].start == (2.0, 0.0, 0.0)  # pied de l'arc au sol


# --- Cartes conservées ------------------------------------------------------------------------


def test_parse_card_is_strict():
    assert parse_card("LD 5 0 0 0 5.8e7").floats[0] == 5.8e7
    for bad in ("GW 1 1 0 0 0 1 0 0 0.001", "LD 5 0 x", "LD 5 0 0 0 nan", "EX " + "1 " * 11, ""):
        with pytest.raises(ValueError):
            parse_card(bad)


def test_card_text_round_trip_and_description():
    trap = Card("LD", (1, 1, 7, 7), (0.0, 4.7e-6, 56e-12, 0.0, 0.0, 0.0))
    assert trap.text() == "LD 1 1 7 7 0 4.7e-06 5.6e-11"
    assert parse_card(trap.text()) == trap
    assert "trappe" in describe_card(trap) and "4,7 µH" in describe_card(trap)
    copper = parse_card("LD 5 0 0 0 5.8e7")
    assert describe_card(copper).startswith("Charge, tous les fils") and "cuivre" in describe_card(
        copper
    )


def test_model_writes_kept_cards_in_order():
    m = AntennaModel(
        wires=[Wire(1, 5, (0, -1, 5), (0, 1, 5), 0.001)],
        excitations=[Excitation(1, 3)],
        ground=Ground("real", exact=False),
        extra_cards=["EX 0 1 1 0 0.5", "LD 5 0 0 0 5.8e+07"],
    )
    lines = m.to_deck().splitlines()
    gn, ld, ex, ex2 = (
        lines.index(x)
        for x in ("GN 0 0 0 0 13 0.005", "LD 5 0 0 0 5.8e+07", "EX 0 1 3 0 1 0", "EX 0 1 1 0 0.5")
    )
    assert gn < ld < ex < ex2  # la source éditable reste la première source du deck


def test_excitation_counts_segments_across_wires_of_same_tag():
    """Arc importé : 8 fils de tag 5 d'un segment chacun → segments 1 à 8 du tag 5."""
    wires = segments_to_wires(parse_segments(OUTPUT))
    m = AntennaModel(wires=wires, excitations=[Excitation(5, 8)])
    assert check_excitations(m) == []
    m.excitations = [Excitation(5, 9)]
    assert "hors limites (1 à 8)" in check_excitations(m)[0]


# --- Refus (avant tout appel à onec) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("deck", "reason"),
    [
        ("", "vide"),
        ("CM\nCE\nSP 0 0 1 1 1 0 0 0.1\nEN\n", "surfaces"),
        ("CM\nCE\nGW 1 3 0 0 1 0 0 2 0.001\nGE\nZZ 1\nEN\n", "carte inconnue « ZZ », ligne 5"),
        (
            "CM\nCE\nGW 1 3 0 0 1 0 0 2 .001\nGE\nEX 0 1 2 0 1\nXQ\nLD 5 0 0 0 5.8e7\nXQ\nEN\n",
            "plusieurs calculs enchaînés (carte LD",
        ),
        ("CM\nCE\nGW 1 3 0 0 1 0 0 2 .001\nGE\nNX\nCM\nCE\nEN\n", "plusieurs modèles"),
        ("CM\nCE\n" + "GW 1 3 0 0 1 0 0 2 0.001\n" * 40_000, "trop gros"),
    ],
)
def test_refusals_before_onec(deck, reason):
    with pytest.raises(ImportRefused, match=re.escape(reason)):
        import_deck(deck)


# --- Avec onec : import complet et fidélité ---------------------------------------------------


@needs_onec
def test_import_4nec2_file():
    r = import_deck(DECK, "yagi.nec")
    m = r.model
    assert (len(m.wires), m.wires[1].tag) == (10, 2)
    assert m.excitations == [Excitation(2, 11, 1.0, 0.0)]
    assert (m.ground.kind, m.ground.epsilon_r, m.ground.exact) == ("real", 13.0, True)
    assert (m.sweep.start_mhz, m.sweep.step_mhz, m.sweep.count) == (14.2, 0.1, 3)
    assert r.frequency_mhz == 14.3
    assert [e.text for e in r.extra] == [
        "LD 5 0 0 0 5.8e+07",
        "LD 1 1 7 7 0 4.7e-06 5.6e-11",
        "EX 0 1 3 0 0.5",
    ]
    assert r.dropped == ["impression des courants (PT)", "diagramme (RP)"]
    assert any("symboles (SY)" in n for n in r.notes)


@needs_onec
def test_import_is_faithful():
    """Le modèle importé et réécrit donne la même impédance que le fichier d'origine
    (trappe et seconde source comprises), point d'alimentation par point d'alimentation."""
    # Référence : le fichier d'origine sans ses cartes d'affichage (onec 2.3.2 ne produit aucun
    # résultat dès qu'une carte PT est présente), calcul lancé par XQ
    original = simulate_deck(strip_execution(DECK).replace("\nEN", "\nXQ 0\nEN"))
    imported = simulate(import_deck(DECK).model)
    for fa, fb in zip(original.frequencies, imported.frequencies, strict=True):
        za = {(p.tag, p.segment): p.impedance for p in fa.feedpoints}
        zb = {(p.tag, p.segment): p.impedance for p in fb.feedpoints}
        assert za.keys() == zb.keys() and len(za) == 2
        for k, z in za.items():
            assert abs(zb[k] - z) / abs(z) < 0.005
        # la source éditable reste en tête (c'est celle que l'interface affiche)
        assert fb.feedpoints[0].tag == 2


@needs_onec
def test_import_defaults_and_variants():
    base = "CM\nCE\nGW 1 11 0 -0.25 1 0 0.25 1 0.001\nGE 0\n"
    r = import_deck(base + "EX 5 1 6 0 1 0\nEN\n")  # source EX 5, pas de FR
    assert r.model.excitations[0].kind == 5
    assert r.model.sweep.start_mhz == 299.8 and any("299,8" in n for n in r.notes)
    r = import_deck(base + "EX 0 0 6 0 1\nFR 0 1 0 0 300\nRP 0 1 1 1000 90 0\nFR 0 1 0 0 310\nEN\n")
    assert r.model.excitations[0].tag == 1  # numéro absolu 6 → fil 1, segment 6
    assert r.model.sweep.start_mhz == 300 and any("premier calcul" in n for n in r.notes)
    with pytest.raises(ImportRefused, match="aucune source"):
        import_deck(base + "EX 1 1 1 0 0 0 0\nEN\n")
