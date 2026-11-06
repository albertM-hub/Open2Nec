"""Cartes NEC conservées telles quelles lors d'un import (LD, TL, NT, EX, EK, KH).

Une carte conservée est une ligne « CODE i1 i2 i3 i4 f1 … f6 » en valeurs numériques (les
symboles 4NEC2 ont déjà été évalués par onec). `parse_card` est aussi le garde-fou de l'API :
seuls ces codes et des nombres sont acceptés, aucune ligne arbitraire ne parvient à onec.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

KEPT_CODES = ("LD", "TL", "NT", "EX", "EK", "KH")
N_INTS = 4
N_FLOATS = 6


@dataclass(frozen=True)
class Card:
    code: str
    ints: tuple[int, int, int, int]
    floats: tuple[float, float, float, float, float, float]

    def text(self) -> str:
        """Ligne NEC ; zéros finaux omis (NEC les complète), 6 chiffres significatifs."""
        fields = [str(i) for i in self.ints] + [f"{f:.6g}" for f in self.floats]
        while len(fields) > 1 and fields[-1] in ("0", "-0"):
            fields.pop()
        return " ".join([self.code, *fields])


def parse_card(text: str) -> Card:
    """Lit une carte conservée. Lève ValueError si elle n'est pas strictement valide."""
    tokens = text.split()
    if not tokens or tokens[0] not in KEPT_CODES:
        raise ValueError(f"carte non autorisée : {text[:20]!r}")
    values = tokens[1:]
    if len(values) > N_INTS + N_FLOATS:
        raise ValueError(f"carte {tokens[0]} : trop de champs")
    try:
        ints = [int(v) for v in values[:N_INTS]]
        floats = [float(v) for v in values[N_INTS:]]
    except ValueError as exc:
        raise ValueError(f"carte {tokens[0]} : valeurs numériques attendues") from exc
    if not all(math.isfinite(f) for f in floats):
        raise ValueError(f"carte {tokens[0]} : valeur non finie")
    ints += [0] * (N_INTS - len(ints))
    floats += [0.0] * (N_FLOATS - len(floats))
    return Card(tokens[0], tuple(ints), tuple(floats))  # type: ignore[arg-type]


def _segments(tag: int, m1: int, m2: int) -> str:
    """Désignation en clair des segments visés (conventions NEC des cartes LD)."""
    if tag == 0 and m1 == 0 and m2 == 0:
        return "tous les fils"
    if tag == 0:
        return f"segments {m1} à {m2} (numérotation globale)"
    if m1 == 0 and m2 == 0:
        return f"fil {tag}, tous les segments"
    return f"fil {tag}, segment {m1}" if m1 == m2 else f"fil {tag}, segments {m1} à {m2}"


def _eng(value: float, unit: str) -> str:
    """Valeur avec préfixe SI (4.7e-6 H → 4,7 µH)."""
    if value == 0:
        return f"0 {unit}"
    for factor, prefix in (
        (1e9, "G"),
        (1e6, "M"),
        (1e3, "k"),
        (1, ""),
        (1e-3, "m"),
        (1e-6, "µ"),
        (1e-9, "n"),
        (1e-12, "p"),
    ):
        if abs(value) >= factor:
            return f"{value / factor:.4g} {prefix}{unit}".replace(".", ",")
    return f"{value:.3g} {unit}"


def describe_card(card: Card) -> str:
    """Description en français, pour la liste des cartes conservées."""
    i1, i2, i3, i4 = card.ints
    f1, f2, f3, *_ = card.floats
    if card.code == "LD":
        where = _segments(i2, i3, i4)
        kinds = {
            0: f"R-L-C série : R {_eng(f1, 'Ω')}, L {_eng(f2, 'H')}, C {_eng(f3, 'F')}",
            1: f"R-L-C parallèle (trappe) : R {_eng(f1, 'Ω')}, L {_eng(f2, 'H')}, "
            f"C {_eng(f3, 'F')}",
            2: f"R-L-C série par mètre : R {_eng(f1, 'Ω/m')}, L {_eng(f2, 'H/m')}, "
            f"C {_eng(f3, 'F/m')}",
            3: f"R-L-C parallèle par mètre : R {_eng(f1, 'Ω/m')}, L {_eng(f2, 'H/m')}, "
            f"C {_eng(f3, 'F/m')}",
            4: f"impédance {f1:.4g} {'+' if f2 >= 0 else '−'} j{abs(f2):.4g} Ω",
            5: f"conductivité du fil σ = {f1:.3g} S/m"
            + (" (cuivre)" if 5.5e7 <= f1 <= 6.0e7 else "")
            + (" (aluminium)" if 3.4e7 <= f1 <= 3.8e7 else ""),
        }
        return f"Charge, {where} — {kinds.get(i1, f'type {i1}')}"
    if card.code == "TL":
        length = "longueur = distance entre les points" if f2 == 0 else f"longueur {f2:.4g} m"
        return (
            f"Ligne de transmission fil {i1} seg. {i2} ↔ fil {i3} seg. {i4}, "
            f"Z0 = {abs(f1):.4g} Ω{' (croisée)' if f1 < 0 else ''}, {length}"
        )
    if card.code == "NT":
        return f"Réseau 2 ports fil {i1} seg. {i2} ↔ fil {i3} seg. {i4}"
    if card.code == "EX":
        if i1 in (0, 5):
            return f"Source supplémentaire fil {i2} seg. {i3}, V = {f1:.4g} {'+' if f2 >= 0 else '−'} j{abs(f2):.4g}"
        if i1 == 6:
            return f"Source de courant fil {i2} seg. {i3}"
        return f"Excitation de type {i1} (onde plane ou dipôle élémentaire)"
    if card.code == "EK":
        return "Noyau étendu (fils épais) " + ("désactivé" if i1 == -1 else "activé")
    if card.code == "KH":
        return f"Intégration approchée au-delà de {f1:.3g} λ"
    return card.text()
