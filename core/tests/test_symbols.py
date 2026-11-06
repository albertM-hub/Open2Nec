"""Symboles SY et formules dans les fils (jalon 6) : règles, résolution par onec, import, export."""

from pathlib import Path

import pytest

from open2nec import AntennaModel, Excitation, FrequencySweep, Wire, simulate
from open2nec.engine import EngineError, ModelRejected, find_onec
from open2nec.importer import import_deck, parse_sy_cards, split_fields, strip_execution
from open2nec.model import Symbol
from open2nec.simulate import simulate_deck
from open2nec.symbols import (
    as_value,
    check_symbols,
    formula_error,
    names_used,
    parse_wire_table,
    resolve,
    validate_with_symbols,
    with_values,
)

DATA = Path(__file__).parent / "data"
SY_DECK = (DATA / "import_symbols_4nec2.nec").read_text()


def _onec_available() -> bool:
    try:
        find_onec()
        return True
    except EngineError:
        return False


needs_onec = pytest.mark.skipif(not _onec_available(), reason="onec absent")

DIPOLE_SYMBOLS = [Symbol("f", "14.2"), Symbol("L", "142.5/f"), Symbol("h", "12")]


def dipole(symbols=True) -> AntennaModel:
    """Dipôle 14,2 MHz en espace libre, en formules ou en nombres (142.5/14.2/2 = 5.01760563…)."""
    half = 142.5 / 14.2 / 2
    if symbols:
        w = Wire(1, 21, (0, "-L/2", "h"), (0, "L/2", "h"), 0.001)
    else:
        w = Wire(1, 21, (0, -half, 12), (0, half, 12), 0.001)
    return AntennaModel(
        wires=[w],
        symbols=list(DIPOLE_SYMBOLS) if symbols else [],
        excitations=[Excitation(1, 11)],
        sweep=FrequencySweep(14.2),
    )


# --- Sans onec ------------------------------------------------------------------------------


def test_deck_writes_sy_then_formulas():
    deck = dipole().to_deck()
    lines = deck.splitlines()
    assert lines[1:5] == ["CE", "SY f=14.2", "SY L=142.5/f", "SY h=12"]
    assert lines[5] == "GW 1 21 0 -L/2 h 0 L/2 h 0.001"


def test_as_value_and_formula_shape():
    assert as_value(" 12.5 ") == 12.5 and as_value(" -L/2 ") == "-L/2" and as_value(3) == 3.0
    assert "espace" in formula_error("L 2")  # pas de « L2 » fabriqué en silence
    assert formula_error("pow(L,2)/2") is None
    assert "virgule" in formula_error("1,2")  # « SY a=1,b=2 » définirait un autre symbole
    assert "retour à la ligne" in formula_error("1\nEN")
    assert "caractère" in formula_error("5'")
    assert "non fermée" in formula_error("(1+2")
    assert "en trop" in formula_error("1+2)")
    assert names_used("-L/2+1ft*sin(a1)+2e-3+_x") == ["l", "a1", "_x"]


@pytest.mark.parametrize(
    ("symbols", "code"),
    [
        ([Symbol("2x", "1")], "symbol-name"),
        ([Symbol("pi", "3")], "symbol-reserved"),
        ([Symbol("_o2n_1", "3")], "symbol-reserved"),
        ([Symbol("a", "1"), Symbol("A", "2")], "symbol-duplicate"),
        ([Symbol("a", "b"), Symbol("b", "1")], "symbol-order"),
        ([Symbol("a", "a+1")], "symbol-order"),
        ([Symbol("a", "1;EN")], "formula-syntax"),
    ],
)
def test_symbol_rules(symbols, code):
    """Règles vérifiées avant onec, qui laisse passer boucles, doublons et noms réservés."""
    issues = check_symbols(AntennaModel(symbols=symbols))
    assert [i.code for i in issues][:1] == [code]
    assert all(i.severity == "error" and i.symbols for i in issues)


def test_wire_formula_shape_checked():
    m = AntennaModel(wires=[Wire(1, 3, (0, 0, 0), (0, 0, "L 2"), 0.001)])
    assert [(i.code, i.wires) for i in check_symbols(m)] == [("formula-syntax", (0,))]


def test_without_formulas_no_onec_call():
    m = dipole(symbols=False)
    assert resolve(m).model is m


def test_with_values():
    m = with_values(dipole(), {"h": 15.25, "F": 7.1})
    assert [s.formula for s in m.symbols] == ["7.1", "142.5/f", "15.25"]
    assert dipole().symbols[2].formula == "12"  # l'original n'est pas modifié


def test_parse_wire_table_ignores_move_lines():
    out = """
  NO.        X1         Y1         Z1          X2         Y2         Z2      RADIUS   SEG.     SEG.   SEG.     NO.
     1    0.00000   -5.01761   12.00000     0.00000    5.01761   12.00000    0.00100     21        1    21       1
     2 ARC RADIUS:   2.00000  FROM:    0.000 TO:   90.000 DEGREES           0.00200     5     0     0    5
   TOTAL SEGMENTS USED=   21     NO. SEG. IN A SYMMETRIC CELL=   21     SYMMETRY FLAG=  0
"""
    assert parse_wire_table(out) == [((0.0, -5.01761, 12.0, 0.0, 5.01761, 12.0), 0.001)]


def test_parse_sy_cards_and_fields():
    syms = parse_sy_cards(SY_DECK)
    names = [s.name for s in syms]
    # Lr cite Ld, défini plus bas : remonté avant lui ; commentaire « ' » retiré
    assert names.index("Ld") < names.index("Lr")
    assert next(s for s in syms if s.name == "Lr").formula == "1.05*Ld"
    assert not check_symbols(AntennaModel(symbols=syms))
    assert split_fields("1 21 -sp,pow(a,2) h") == ["1", "21", "-sp", "pow(a,2)", "h"]


# --- Avec onec ------------------------------------------------------------------------------


@needs_onec
def test_resolve_dipole():
    res = resolve(dipole())
    assert res.values == {"f": 14.2, "L": 10.0352, "h": 12.0}  # 6 chiffres significatifs
    w = res.model.wires[0]
    assert w.start == (0.0, -5.01761, 12.0) and w.end == (0.0, 5.01761, 12.0)
    assert res.model.symbols == []


@needs_onec
def test_formulas_simulate_like_numbers():
    """onec calcule les formules : même impédance qu'avec les nombres, au centième d'ohm."""
    za = simulate(dipole()).frequencies[0].feedpoints[0].impedance
    zb = simulate(dipole(symbols=False)).frequencies[0].feedpoints[0].impedance
    assert abs(za - zb) < 0.01


@needs_onec
def test_radius_formula_keeps_precision():
    m = dipole()
    m.symbols.append(Symbol("r", "0.000127"))
    m.wires[0].radius = "r"
    assert resolve(m).model.wires[0].radius == pytest.approx(0.000127)


@needs_onec
@pytest.mark.parametrize(
    ("formula", "code", "text"),
    [
        ("L*q", "formula-eval", "fil 1, z2"),  # onec remplacerait par 0 sans rien dire
        ("L**2", "formula-eval", "fil 1, z2"),
        ("h/0", "formula-infinite", "fil 1, z2"),
    ],
)
def test_wire_formula_errors(formula, code, text):
    m = dipole()
    m.wires[0].end = (0, "L/2", formula)
    issues = resolve(m).issues
    assert [(i.code, i.wires) for i in issues] == [(code, (0,))] and text in issues[0].message


@needs_onec
def test_symbol_formula_errors():
    m = dipole()
    m.symbols[2] = Symbol("h", "zz*2")
    (issue,) = resolve(m).issues
    assert issue.code == "formula-eval" and issue.symbols == (2,) and "« h »" in issue.message
    m.symbols[2] = Symbol("h", "1/0")
    (issue,) = resolve(m).issues
    assert issue.code == "formula-infinite" and issue.symbols == (2,)


@pytest.mark.parametrize(
    "message",
    [
        "Error evaluating formula 'zz*2' at position 2 on card 5",  # onec 2.3.3
        "Error evaluating formula 'h = zz*2' on card 5 at position 2",  # onec 2.3.4
    ],
)
def test_eval_error_read_from_both_onec_formats(monkeypatch, message):
    def rejected(*_args, **_kwargs):
        raise ModelRejected(f"onec a refusé le modèle : {message}")

    monkeypatch.setattr("open2nec.symbols.run_onec", rejected)
    m = dipole()
    m.symbols[2] = Symbol("h", "zz*2")
    (issue,) = resolve(m).issues
    assert issue.code == "formula-eval" and issue.symbols == (2,)
    assert "« h »" in issue.message and "formule « zz*2 »" in issue.message


@needs_onec
def test_validate_with_symbols_checks_resolved_geometry():
    m = dipole()
    m.symbols[2] = Symbol("h", "0")
    m.ground.kind = "perfect"  # fil couché sur le sol : erreur du contrôle du modèle
    res, issues = validate_with_symbols(m, 14.2)
    assert res.model is not None and any(i.severity == "error" for i in issues)
    m.symbols[2] = Symbol("h", "12")
    assert not [i for i in validate_with_symbols(m, 14.2)[1] if i.severity == "error"]


@needs_onec
def test_import_keeps_symbols_and_formulas():
    r = import_deck(SY_DECK, "yagi3.nec")
    m = r.model
    assert {s.name for s in m.symbols} == {"f", "Lr", "Ld", "Ldir", "sp", "h", "r"}
    assert m.wires[0] == Wire(1, 21, ("-sp", "-Lr/2", "h"), ("-sp", "Lr/2", "h"), "r")
    assert m.wires[2].start == ("sp", "-Ldir/2", "h")
    # l'arc GA reste en nombres, signalé
    assert all(not w.has_formula for w in m.wires[3:]) and len(m.wires) > 3
    assert any("GA" in n for n in r.notes)
    assert any("FR" in n for n in r.notes)  # FR f garde sa valeur
    assert not any("remplacés" in n for n in r.notes)


@needs_onec
def test_import_symbols_round_trip_is_faithful():
    """Fichier → modèle → .nec réenregistré : SY et formules réécrits, même impédance."""
    r = import_deck(SY_DECK)
    deck = r.model.to_deck()
    assert "SY Lr=1.05*Ld" in deck and "GW 2 21 0 -Ld/2 h 0 Ld/2 h r" in deck
    original = simulate_deck(strip_execution(SY_DECK).replace("\nEN", "\nXQ 0\nEN"))
    again = simulate(import_deck(deck).model)
    for fa, fb in zip(original.frequencies, again.frequencies, strict=True):
        za, zb = fa.feedpoints[0].impedance, fb.feedpoints[0].impedance
        assert abs(zb - za) / abs(za) < 0.005


@needs_onec
def test_import_with_copies_freezes_values():
    r = import_deck((DATA / "import_yagi_4nec2.nec").read_text())
    assert r.model.symbols == [] and not any(w.has_formula for w in r.model.wires)
    assert any("GM" in n and "remplacés" in n for n in r.notes)
