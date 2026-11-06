"""Symboles (cartes SY) et formules 4NEC2 dans les cases des fils.

On ne réimplémente pas l'évaluateur de 4NEC2 : onec calcule les formules. Pour connaître les
valeurs (vue 3D, contrôle du modèle, tableau des symboles), on lui fait lire un deck « sonde »
sans calcul (aucune carte d'exécution, quelques ms) :
  - la table des fils (WIRE … X1 Y1 Z1 X2 Y2 Z2 RADIUS) donne les extrémités calculées de chaque
    carte GW, à 10 µm près (5 décimales) — la même précision que l'import ;
  - une carte « FR 0 1 0 0 <formule> 0 » par symbole et par rayon en formule : onec recopie la
    valeur calculée dans sa ligne DATA CARD, à 6 chiffres significatifs (un rayon de 0,127 mm
    n'aurait que 2 chiffres dans la table des fils).

onec 2.3.3 laisse passer sans rien dire plusieurs erreurs de symboles (vérifié le 2026-11-04) :
boucle « a=b, b=a » → 0 ; doublon → le premier gagne ; « 1/0 » → INF ; noms insensibles à la
casse ; « pi » ou « sin » redéfinissables. D'où les règles vérifiées ici, avant onec : nom
unique (casse ignorée), non réservé, défini avant d'être utilisé (ce qui exclut les boucles),
formule faite des seuls caractères attendus. Les fonctions trigonométriques d'onec sont en
degrés (sin(30) = 0,5), comme dans 4NEC2.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace

from .engine import ModelRejected, run_onec
from .model import AntennaModel, Symbol, Value, Wire
from .validate import Issue, validate_model

RESOLVE_TIMEOUT_S = 30.0
MAX_FORMULA_LENGTH = 200

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")
# Fonctions et constantes d'onec (manuel OpenNEC et essais) : refusées comme noms de symboles
RESERVED = frozenset(
    [
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "atn",
        "sqr",
        "sqrt",
        "pow",
        "abs",
        "log",
        "log10",
        "exp",
        "int",
        "ceil",
        "floor",
        "round",
        "pi",
    ]
)
# Caractères d'une formule : pas d'espace (il séparerait les champs de la carte), pas de « ' »
# ni de « # » (commentaires selon les logiciels), pas de « ; » ni de retour à la ligne.
_FORMULA_CHARS_RE = re.compile(r"^[A-Za-z0-9_.+\-*/^(),]+$")
# Nom utilisé dans une formule : pas précédé d'un chiffre (« 1ft », « 2e-3 » sont des nombres),
# pas suivi de « ( » (appel de fonction).
_IDENT_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(?!\w|\s*\()")
# onec 2.3.3 : « 'zz*2' at position 2 on card 4 ».
# onec 2.3.4 : « 'h = zz*2' on card 4 at position 2 », « 'L*q' for F6 on card 4 at position 3 ».
# Le « nom = » est retiré : le nom affiché vient du modèle, et celui d'un symbole auxiliaire
# (_o2n_n) ne doit pas atteindre l'utilisateur.
_EVAL_ERROR_RE = re.compile(
    r"Error evaluating formula '(?:\w+ = )?(.*)'(?: for \w+)?(?: at position \d+)? on card (\d+)"
)
_FLOAT_RE = re.compile(r"-?\d+\.\d{5}(?!\d)")
_WIRE_ROW_RE = re.compile(r"^\s*(\d+)\s+(-?\d.*)$")
_DATA_FR_RE = re.compile(r"DATA CARD No:\s*\d+\s+FR\s+\S+\s+\S+\s+\S+\s+\S+\s+(\S+)")


def is_number(text: str) -> bool:
    try:
        return math.isfinite(float(text))
    except ValueError:
        return False


def as_value(v: Value) -> Value:
    """« 12.5 » → 12.5 ; formule gardée en texte. Seuls les espaces des bords sont retirés :
    « L 2 » ne doit pas devenir le symbole « L2 » (formula_error le refuse)."""
    if isinstance(v, str):
        v = v.strip()
        return float(v) if is_number(v) else v
    return float(v)


def formula_error(formula: str) -> str | None:
    """Défaut de forme d'une formule (avant onec), ou None."""
    if not formula:
        return "formule vide"
    if len(formula) > MAX_FORMULA_LENGTH:
        return f"formule trop longue (maximum {MAX_FORMULA_LENGTH} caractères)"
    if any(c.isspace() for c in formula):
        return "espace ou retour à la ligne dans la formule"
    if not _FORMULA_CHARS_RE.match(formula):
        bad = sorted({c for c in formula if not _FORMULA_CHARS_RE.match(c)})
        return "caractère non permis : " + " ".join(repr(c) for c in bad)
    depth = 0
    for c in formula:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                return "parenthèse fermante en trop"
        elif c == "," and depth == 0:
            # « SY a=1, b=2 » : une virgule hors parenthèses définirait un autre symbole
            return "virgule hors d'une fonction"
    if depth:
        return "parenthèse non fermée"
    return None


def names_used(formula: str) -> list[str]:
    """Noms (minuscules) cités dans une formule, hors fonctions et suffixes d'unités."""
    return [m.group(1).lower() for m in _IDENT_RE.finditer(formula)]


# --- Contrôles de structure (sans onec) -----------------------------------------------------


def check_symbols(model: AntennaModel) -> list[Issue]:
    """Règles des symboles et forme des formules ; erreurs uniquement."""
    issues: list[Issue] = []
    defined: dict[str, int] = {}  # nom en minuscules → rang
    all_names = {s.name.lower(): i for i, s in enumerate(model.symbols)}
    for i, sym in enumerate(model.symbols):
        where = (i,)
        if not NAME_RE.match(sym.name):
            issues.append(
                Issue(
                    "error",
                    "symbol-name",
                    f"nom de symbole invalide « {sym.name} » : une lettre ou « _ », puis "
                    "lettres, chiffres ou « _ » (32 au plus)",
                    symbols=where,
                )
            )
            continue
        low = sym.name.lower()
        if low in RESERVED or low.startswith(AUX_PREFIX):
            issues.append(
                Issue(
                    "error",
                    "symbol-reserved",
                    f"« {sym.name} » est un nom réservé (fonction, constante d'onec ou "
                    f"préfixe {AUX_PREFIX}) : choisir un autre nom",
                    symbols=where,
                )
            )
        if low in defined:
            issues.append(
                Issue(
                    "error",
                    "symbol-duplicate",
                    f"symbole « {sym.name} » défini deux fois (majuscules et minuscules "
                    "sont confondues)",
                    symbols=(defined[low], i),
                )
            )
        if err := formula_error(sym.formula):
            issues.append(
                Issue("error", "formula-syntax", f"symbole « {sym.name} » : {err}", symbols=where)
            )
        else:
            for used in names_used(sym.formula):
                if used == low:
                    issues.append(
                        Issue(
                            "error",
                            "symbol-order",
                            f"symbole « {sym.name} » : il se cite lui-même",
                            symbols=where,
                        )
                    )
                elif used not in defined and all_names.get(used, -1) > i:
                    issues.append(
                        Issue(
                            "error",
                            "symbol-order",
                            f"symbole « {sym.name} » : utilise « {used} », défini plus bas "
                            "(le placer avant)",
                            symbols=(i, all_names[used]),
                        )
                    )
        defined.setdefault(low, i)

    for row, wire in enumerate(model.wires):
        for v in (*wire.start, *wire.end, wire.radius):
            if isinstance(v, str) and (err := formula_error(v)):
                issues.append(
                    Issue(
                        "error",
                        "formula-syntax",
                        f"fil {row + 1}, formule « {v} » : {err}",
                        wires=(row,),
                    )
                )
    return issues


# --- Résolution par onec --------------------------------------------------------------------


@dataclass
class Resolved:
    """Modèle en nombres (None en cas d'erreur), valeurs des symboles, erreurs trouvées."""

    model: AntennaModel | None
    values: dict[str, float] = field(default_factory=dict)  # nom tel que saisi → valeur
    issues: list[Issue] = field(default_factory=list)


AUX_PREFIX = "_o2n_"  # symboles auxiliaires du deck sonde ; préfixe interdit aux utilisateurs


def _formula_fields(model: AntennaModel) -> list[tuple[int, int, str]]:
    """(rang du fil, case 0–6 : x1 y1 z1 x2 y2 z2 rayon, formule) de chaque case en formule."""
    out = []
    for row, w in enumerate(model.wires):
        for k, v in enumerate((*w.start, *w.end, w.radius)):
            if isinstance(v, str):
                out.append((row, k, v))
    return out


def probe_deck(model: AntennaModel) -> tuple[str, list[tuple[int, int, str]]]:
    """Deck de lecture sans calcul, et les cases en formule dans l'ordre des sondes.

    Dans une carte GW, onec 2.3.3 remplace sans rien dire une formule invalide par 0 (« L*q »
    avec q inconnu, « (1+ ») ; dans une carte SY, il la refuse. Chaque formule de fil passe donc
    aussi par un symbole auxiliaire, contrôlé et mesuré par une sonde FR. Ordre des sondes :
    les symboles, puis les auxiliaires.
    """
    fields = _formula_fields(model)
    lines = ["CM sonde Open2Nec", "CE"]
    lines += [s.card() for s in model.symbols]
    lines += [f"SY {AUX_PREFIX}{n}={f}" for n, (_, _, f) in enumerate(fields)]
    lines += [w.card() for w in model.wires]
    lines.append("GE 0")  # sol sans effet ici ; évite les refus « sous le sol » (et #30)
    lines += [f"FR 0 1 0 0 {s.name} 0" for s in model.symbols]
    lines += [f"FR 0 1 0 0 {AUX_PREFIX}{n} 0" for n in range(len(fields))]
    lines.append("EN")
    return "\n".join(lines) + "\n", fields


def parse_wire_table(output: str) -> list[tuple[tuple[float, ...], float]]:
    """Lignes de la table des fils : ((x1, y1, z1, x2, y2, z2), rayon), une par carte GW."""
    rows: list[tuple[tuple[float, ...], float]] = []
    in_table = False
    for line in output.splitlines():
        if "X1" in line and "Y1" in line and "Z2" in line:
            in_table = True
            continue
        if in_table and "TOTAL SEGMENTS USED" in line:
            break
        if not in_table:
            continue
        m = _WIRE_ROW_RE.match(line)
        floats = _FLOAT_RE.findall(m.group(2)) if m else []
        if len(floats) == 7:
            v = [float(f) for f in floats]
            rows.append((tuple(v[:6]), v[6]))
    return rows


def parse_probe_values(output: str) -> list[float]:
    """Première valeur de chaque ligne DATA CARD FR (INF/NAN compris)."""
    return [float(m.group(1)) for m in map(_DATA_FR_RE.search, output.splitlines()) if m]


_FIELD_NAMES = ("x1", "y1", "z1", "x2", "y2", "z2", "rayon")


def _card_issue(model: AntennaModel, card: int, formula: str) -> Issue:
    """Erreur d'évaluation sur la carte n° `card` du deck sonde, en clair."""
    ns = len(model.symbols)
    fields = _formula_fields(model)
    tail = f"formule « {formula} » incalculable (nom inconnu ou syntaxe)"
    if 3 <= card < 3 + ns:
        i = card - 3
        return Issue(
            "error", "formula-eval", f"symbole « {model.symbols[i].name} » : {tail}", symbols=(i,)
        )
    if 3 + ns <= card < 3 + ns + len(fields):
        row, k, _ = fields[card - 3 - ns]
        return Issue(
            "error", "formula-eval", f"fil {row + 1}, {_FIELD_NAMES[k]} : {tail}", wires=(row,)
        )
    return Issue("error", "formula-eval", f"carte {card} : {tail}")


def resolve(model: AntennaModel) -> Resolved:
    """Évalue symboles et formules par onec. Sans formule : modèle inchangé, sans appel."""
    issues = check_symbols(model)
    if issues:
        return Resolved(None, issues=issues)
    if not model.has_formulas:
        return Resolved(model)

    deck, fields = probe_deck(model)
    try:
        output = run_onec(deck, timeout=RESOLVE_TIMEOUT_S)
    except ModelRejected as exc:
        m = _EVAL_ERROR_RE.search(str(exc))
        if not m:
            return Resolved(None, issues=[Issue("error", "formula-eval", str(exc))])
        return Resolved(None, issues=[_card_issue(model, int(m.group(2)), m.group(1))])

    values = parse_probe_values(output)
    ns = len(model.symbols)
    if len(values) != ns + len(fields):
        raise ModelRejected(
            f"sortie d'onec inattendue : {len(values)} valeurs sur {ns + len(fields)}"
        )
    sym_values = {s.name: v for s, v in zip(model.symbols, values[:ns], strict=True)}
    radii = {row: v for (row, k, _), v in zip(fields, values[ns:], strict=True) if k == 6}
    for i, s in enumerate(model.symbols):
        if not math.isfinite(sym_values[s.name]):
            issues.append(
                Issue(
                    "error",
                    "formula-infinite",
                    f"symbole « {s.name} » : valeur infinie ou indéfinie (division par zéro ?)",
                    symbols=(i,),
                )
            )
    # un symbole infini rend infinies les cases qui le citent : seule sa remarque compte
    symbol_infinite = bool(issues)
    for (row, k, f), v in zip(fields, values[ns:], strict=True):
        if not math.isfinite(v) and not symbol_infinite:
            issues.append(
                Issue(
                    "error",
                    "formula-infinite",
                    f"fil {row + 1}, {_FIELD_NAMES[k]} : « {f} » donne une valeur infinie ou "
                    "indéfinie (division par zéro ?)",
                    wires=(row,),
                )
            )
    if issues:  # la table des fils contient alors des « INF » illisibles
        return Resolved(None, sym_values, issues)
    table = parse_wire_table(output)
    if len(table) != len(model.wires):
        raise ModelRejected(
            f"sortie d'onec inattendue : {len(table)} fils lus sur {len(model.wires)}"
        )

    wires: list[Wire] = []
    for row, (w, (coords, table_radius)) in enumerate(zip(model.wires, table, strict=True)):
        cells = [*w.start, *w.end]
        nums = [c if isinstance(f, str) else float(f) for f, c in zip(cells, coords, strict=True)]
        radius = radii.get(row, table_radius) if isinstance(w.radius, str) else float(w.radius)
        if not math.isfinite(radius) or radius <= 0:
            issues.append(
                Issue(
                    "error",
                    "formula-radius",
                    f"fil {row + 1} : le rayon calculé ({radius:g} m) doit être positif",
                    wires=(row,),
                )
            )
        wires.append(Wire(w.tag, w.segments, tuple(nums[:3]), tuple(nums[3:]), radius))  # type: ignore[arg-type]
    if issues:
        return Resolved(None, sym_values, issues)
    return Resolved(replace(model, wires=wires, symbols=[]), sym_values)


def validate_with_symbols(
    model: AntennaModel, max_frequency_mhz: float
) -> tuple[Resolved, list[Issue]]:
    """Contrôle complet : symboles et formules, puis contrôle du modèle résolu."""
    res = resolve(model)
    if res.model is None:
        return res, res.issues
    return res, validate_model(res.model, max_frequency_mhz)


def with_values(model: AntennaModel, values: dict[str, float]) -> AntennaModel:
    """Copie du modèle où les symboles nommés valent les nombres donnés (optimiseur, Appliquer)."""
    lower = {k.lower(): v for k, v in values.items()}
    symbols = [
        Symbol(s.name, repr(float(lower[s.name.lower()]))) if s.name.lower() in lower else s
        for s in model.symbols
    ]
    return replace(model, symbols=symbols)


__all__ = [
    "RESERVED",
    "Resolved",
    "Symbol",
    "as_value",
    "check_symbols",
    "formula_error",
    "names_used",
    "resolve",
    "validate_with_symbols",
    "with_values",
]
