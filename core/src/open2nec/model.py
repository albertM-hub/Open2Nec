"""Modèle d'antenne et génération du deck NEC.

Unités : mètres, MHz. Le modèle ne dépend d'aucune interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Une case de fil : un nombre, ou une formule 4NEC2 (« -L/2 ») évaluée par onec à partir des
# symboles (voir symbols.py). Les contrôles et la vue 3D travaillent sur le modèle « résolu »,
# où toutes les cases sont des nombres.
Value = float | str
Point = tuple[Value, Value, Value]


def fmt_value(v: Value) -> str:
    """Case de carte NEC. Nombres : 10 chiffres significatifs (« :g » seul n'en garde que 6,
    ce qui arrondit par ex. 432.1745 MHz en 432.175). Formules : recopiées telles quelles."""
    return v if isinstance(v, str) else f"{v:.10g}"


@dataclass
class Symbol:
    """Symbole 4NEC2 (carte SY) : nom = formule (« 12 », « 142.5/f »)."""

    name: str
    formula: str

    def card(self) -> str:
        return f"SY {self.name}={self.formula}"


@dataclass
class Wire:
    """Un fil droit (carte GW)."""

    tag: int
    segments: int
    start: Point
    end: Point
    radius: Value

    def card(self) -> str:
        values = (*self.start, *self.end, self.radius)
        return f"GW {self.tag} {self.segments} " + " ".join(fmt_value(v) for v in values)

    @property
    def has_formula(self) -> bool:
        return any(isinstance(v, str) for v in (*self.start, *self.end, self.radius))

    @property
    def length(self) -> float:
        """Longueur ; seulement pour un fil sans formule (modèle résolu)."""
        return sum((a - b) ** 2 for a, b in zip(self.start, self.end)) ** 0.5  # type: ignore[operator]


@dataclass
class Excitation:
    """Source de tension sur un segment (carte EX).

    kind 0 : tension appliquée (cas courant) ; kind 5 : tension à discontinuité de la dérivée
    du courant, variante présente dans certains fichiers NEC-2 et conservée à l'import.
    """

    tag: int
    segment: int
    voltage_re: float = 1.0
    voltage_im: float = 0.0
    kind: int = 0

    def card(self) -> str:
        return (
            f"EX {self.kind} {self.tag} {self.segment} 0 "
            f"{self.voltage_re:.10g} {self.voltage_im:.10g}"
        )


@dataclass
class Ground:
    """Sol : 'free' (espace libre), 'perfect' ou 'real'.

    Sol réel : `exact` = solution de Sommerfeld/Norton (GN 2, recommandée) ; sinon approximation
    par coefficient de réflexion (GN 0, plus rapide, utilisée par certains fichiers 4NEC2).
    """

    kind: str = "free"
    epsilon_r: float = 13.0
    conductivity: float = 0.005  # S/m
    exact: bool = True

    def card(self) -> str | None:
        if self.kind == "free":
            return None
        if self.kind == "perfect":
            return "GN 1"
        if self.kind == "real":
            kind = 2 if self.exact else 0
            return f"GN {kind} 0 0 0 {self.epsilon_r:.10g} {self.conductivity:.10g}"
        raise ValueError(f"type de sol inconnu : {self.kind!r}")


@dataclass
class FrequencySweep:
    """Balayage linéaire (carte FR)."""

    start_mhz: float
    step_mhz: float = 0.0
    count: int = 1

    def card(self) -> str:
        return f"FR 0 {self.count} 0 0 {self.start_mhz:.10g} {self.step_mhz:.10g}"

    @property
    def frequencies(self) -> list[float]:
        # arrondi au mHz : évite 14.200000000000001 (cumul flottant de start + i × step)
        return [round(self.start_mhz + i * self.step_mhz, 9) for i in range(self.count)]


@dataclass
class RadiationGrid:
    """Grille du diagramme de rayonnement (carte RP), à partir de (theta0, phi0) en degrés."""

    n_theta: int = 37
    n_phi: int = 73
    d_theta: float = 5.0
    d_phi: float = 5.0
    theta0: float = 0.0
    phi0: float = 0.0

    def card(self) -> str:
        return (
            f"RP 0 {self.n_theta} {self.n_phi} 1000 {self.theta0:.10g} {self.phi0:.10g} "
            f"{self.d_theta:.10g} {self.d_phi:.10g}"
        )


@dataclass
class AntennaModel:
    wires: list[Wire] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    excitations: list[Excitation] = field(default_factory=list)
    ground: Ground = field(default_factory=Ground)
    sweep: FrequencySweep = field(default_factory=lambda: FrequencySweep(14.2))
    pattern: RadiationGrid | None = None
    comment: str = "Genere par Open2Nec"
    # Cartes NEC conservées d'un fichier importé (LD, TL, NT, EX supplémentaires, EK, KH), en
    # valeurs numériques ; validées par cards.parse_card. Écrites entre le sol et la source.
    extra_cards: list[str] = field(default_factory=list)

    def to_deck(self) -> str:
        """Génère le texte du deck NEC.

        Ordre des cartes : CM, CE, SY, GW, GE, GN, cartes conservées (LD, TL…), EX, EX conservées,
        FR, RP (ou XQ), EN.
        """
        comment = " ".join(self.comment.split())  # une seule ligne, quoi qu'il arrive
        lines = [f"CM {comment}", "CE"]
        lines += [s.card() for s in self.symbols]
        lines += [w.card() for w in self.wires]
        lines.append("GE 1" if self.ground.kind != "free" else "GE 0")
        gn = self.ground.card()
        if gn:
            lines.append(gn)
        # Source(s) éditable(s) avant les EX conservées : onec liste les points d'alimentation
        # dans l'ordre des cartes EX, et le premier est celui que l'interface affiche.
        is_ex = [c.split()[0] == "EX" for c in self.extra_cards]
        lines += [c for c, ex in zip(self.extra_cards, is_ex, strict=True) if not ex]
        lines += [e.card() for e in self.excitations]
        lines += [c for c, ex in zip(self.extra_cards, is_ex, strict=True) if ex]
        lines.append(self.sweep.card())
        # NEC-2 ne calcule rien sans carte d'exécution : RP (avec diagramme) ou XQ (sans).
        # Sans elle, onec lit le deck puis s'arrête sans résultat.
        lines.append(self.pattern.card() if self.pattern else "XQ 0")
        lines.append("EN")
        return "\n".join(lines) + "\n"

    @property
    def has_formulas(self) -> bool:
        return bool(self.symbols) or any(w.has_formula for w in self.wires)
