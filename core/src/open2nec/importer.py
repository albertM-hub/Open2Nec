"""Import d'un fichier .nec (4NEC2, NEC-2) en AntennaModel éditable.

On ne réimplémente pas l'évaluateur de 4NEC2 (symboles SY, formules, GM/GR/GA…) : on fait lire
le fichier par onec *sans lancer de calcul* (cartes d'exécution retirées, quelques ms), puis on
relit ce qu'il a compris dans sa sortie :
  - la table SEGMENTATION DATA : géométrie développée, segment par segment ;
  - les lignes « DATA CARD » : cartes de commande avec leurs valeurs numériques.
Les segments alignés et contigus d'un même tag sont regroupés en fils. Les cartes électriques que
l'éditeur ne gère pas (LD, TL, NT…) sont conservées telles quelles ; une carte inconnue fait
refuser le fichier, pour ne jamais simuler en silence autre chose que ce qu'il décrit.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .cards import KEPT_CODES, Card, describe_card
from .engine import ModelRejected, run_onec
from .model import AntennaModel, Excitation, FrequencySweep, Ground, Symbol, Wire

# Cartes de géométrie : développées par onec, relues via la table des segments
GEOMETRY_CODES = {"GW", "GA", "GH", "GM", "GR", "GX", "GS", "GC", "GE", "CM", "CE", "SY", "EN"}
# Cartes d'exécution ou d'affichage : retirées avant lecture, sans effet sur le modèle
DROPPED_CODES = {
    "RP": "diagramme (RP)",
    "XQ": "exécution (XQ)",
    "NE": "champ proche E (NE)",
    "NH": "champ proche H (NH)",
    "PT": "impression des courants (PT)",
    "PQ": "impression des charges (PQ)",
    "PL": "options de tracé (PL)",
    "WG": "écriture des fonctions de Green (WG)",
    "CP": "couplage entre segments (CP)",
}
# Cartes que le modèle ne sait pas représenter : refus motivé
REFUSED_CODES = {
    "SP": "surfaces (SP)",
    "SM": "surfaces (SM)",
    "SC": "surfaces (SC)",
    "GF": "fonctions de Green lues sur fichier (GF)",
    "GD": "second milieu de sol (GD)",
    "NX": "plusieurs modèles dans un même fichier (NX)",
    "XT": "fin de calcul anticipée (XT)",
}
HANDLED_CODES = {"GN", "FR"} | set(KEPT_CODES)
# Cartes qui lancent un calcul ; une carte de commande placée après l'une d'elles signale un
# fichier à plusieurs calculs enchaînés, que le modèle (un seul calcul) ne sait pas représenter
EXECUTION_CODES = {"RP", "XQ", "NE", "NH"}
COMMAND_CODES = {"GN", "FR", "EX", "LD", "TL", "NT", "EK", "KH"}
# Fréquence de NEC-2 en l'absence de carte FR
NEC_DEFAULT_MHZ = 299.8

MAX_IMPORT_BYTES = 1_000_000
IMPORT_TIMEOUT_S = 30.0

# Un code de carte : 2 lettres en début de ligne, suivies d'un séparateur ou directement d'un
# nombre (« EX2,0,1 » existe). Une ligne de continuation commençant par un nom de symbole
# (« lam/2 ») n'est pas prise pour une carte.
_CODE_RE = re.compile(r"^\s*([A-Za-z]{2})(?=[\s,\d.+-]|$)")
# Les flottants de la table des segments ont toujours 5 décimales (%10.5f) mais peuvent être
# collés quand la colonne est pleine : « 84.37500-180.00000 ». On les repère donc par leur forme.
_SEG_FLOAT_RE = re.compile(r"-?\d+\.\d{5}(?!\d)")
_SEG_LINE_RE = re.compile(r"^\s*(\d+)\s*(-?\d.*)$")
_DATA_CARD_RE = re.compile(r"DATA CARD No:\s*\d+\s+([A-Z]{2})\s+(.*)$")


class ImportRefused(ModelRejected):
    """Fichier lisible mais non représentable par le modèle (surfaces, carte inconnue…)."""


@dataclass
class Segment:
    number: int
    center: tuple[float, float, float]
    length: float
    alpha: float  # élévation de l'axe du segment, degrés
    beta: float  # azimut de l'axe du segment, degrés
    radius: float
    tag: int

    def direction(self) -> tuple[float, float, float]:
        a, b = math.radians(self.alpha), math.radians(self.beta)
        return (math.cos(a) * math.cos(b), math.cos(a) * math.sin(b), math.sin(a))

    def ends(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        d = self.direction()
        h = self.length / 2
        start = tuple(c - h * k for c, k in zip(self.center, d, strict=True))
        end = tuple(c + h * k for c, k in zip(self.center, d, strict=True))
        return start, end  # type: ignore[return-value]


@dataclass
class ExtraCard:
    text: str
    description: str


@dataclass
class ImportResult:
    model: AntennaModel
    frequency_mhz: float  # fréquence proposée pour le diagramme (centre du balayage)
    extra: list[ExtraCard] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)  # cartes écartées, en clair
    notes: list[str] = field(default_factory=list)  # ce que l'utilisateur doit savoir


# --- Lecture du fichier d'origine ---------------------------------------------------------


def card_codes(deck: str) -> list[tuple[int, str]]:
    """(numéro de ligne, code) de chaque carte, commentaires 4NEC2 (« ' ») ignorés."""
    out = []
    for n, line in enumerate(deck.splitlines(), start=1):
        if line.lstrip().startswith(("'", "!")):
            continue
        m = _CODE_RE.match(line)
        if m:
            out.append((n, m.group(1).upper()))
    return out


def strip_execution(deck: str) -> str:
    """Retire les cartes d'exécution et d'affichage : onec lit alors le fichier sans calculer."""
    kept = []
    for line in deck.splitlines():
        m = _CODE_RE.match(line)
        if m and m.group(1).upper() in DROPPED_CODES:
            continue
        kept.append(line)
    return "\n".join(kept) + "\n"


# --- Lecture de la sortie de onec ---------------------------------------------------------


def parse_segments(output: str) -> list[Segment]:
    """Table SEGMENTATION DATA (format « original » de onec)."""
    lines = output.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if "SEGMENTATION DATA" in ln)
    except StopIteration:
        return []
    segments: list[Segment] = []
    for line in lines[start + 1 :]:
        m = _SEG_LINE_RE.match(line)
        floats = _SEG_FLOAT_RE.findall(m.group(2)) if m else []
        if not m or len(floats) < 7:
            if segments and line.strip():
                break  # fin de la table
            continue
        # après le 7e flottant : I-, I, I+, TAG
        tail = m.group(2)
        for f in floats[:7]:
            tail = tail[tail.index(f) + len(f) :]
        ints = tail.split()
        if len(ints) < 4:
            raise ModelRejected(f"table des segments illisible : {line.strip()!r}")
        x, y, z, length, alpha, beta, radius = (float(f) for f in floats[:7])
        segments.append(
            Segment(int(m.group(1)), (x, y, z), length, alpha, beta, radius, int(ints[3]))
        )
    return segments


def parse_data_cards(output: str) -> list[Card]:
    """Lignes « DATA CARD No: n CODE i1 i2 i3 i4 f1 … f6 » (valeurs évaluées par onec)."""
    cards = []
    for line in output.splitlines():
        m = _DATA_CARD_RE.search(line)
        if not m or m.group(1) == "EN":
            continue
        values = m.group(2).split()
        ints = tuple(int(v) for v in values[:4])
        floats = tuple(float(v) for v in values[4:10])
        floats += (0.0,) * (6 - len(floats))
        cards.append(Card(m.group(1), ints, floats))  # type: ignore[arg-type]
    return cards


# --- Symboles et formules ---------------------------------------------------------------

# Cartes qui copient, déplacent ou mettent à l'échelle des fils déjà définis : les formules d'un
# fil d'origine ne suivraient pas ses copies, on ne garde alors aucune formule.
TRANSFORM_CODES = {"GM", "GR", "GX", "GS"}


def split_fields(text: str) -> list[str]:
    """Champs d'une carte : séparés par espaces ou virgules, hors parenthèses (« pow(a,b) »)."""
    fields: list[str] = []
    cur = ""
    depth = 0
    for c in text:
        if c in "()":
            depth += 1 if c == "(" else -1
        if (c.isspace() or c == ",") and depth == 0:
            if cur:
                fields.append(cur)
            cur = ""
        else:
            cur += c
    if cur:
        fields.append(cur)
    return fields


def parse_sy_cards(deck: str) -> list[Symbol]:
    """Symboles des cartes SY (« SY f=14.2, L=142.5/f ' commentaire »), dans l'ordre."""
    from .symbols import names_used  # import local : symbols importe ce module (cycle)

    symbols: list[Symbol] = []
    for line in deck.splitlines():
        m = _CODE_RE.match(line)
        if not m or m.group(1).upper() != "SY":
            continue
        body = line[m.end() :].split("'", 1)[0]
        depth = 0
        part = ""
        parts: list[str] = []
        for c in body:  # virgules hors parenthèses
            depth += {"(": 1, ")": -1}.get(c, 0)
            if c == "," and depth == 0:
                parts.append(part)
                part = ""
            else:
                part += c
        parts.append(part)
        for p in parts:
            if "=" in p:
                name, formula = p.split("=", 1)
                symbols.append(Symbol(name.strip(), "".join(formula.split())))
    # Un symbole qui en cite un autre défini plus bas (onec l'accepte) : on remonte ce dernier.
    by_name = {s.name.lower(): s for s in symbols}
    ordered: list[Symbol] = []
    visiting: set[str] = set()

    def visit(s: Symbol) -> None:
        key = s.name.lower()
        if s in ordered or key in visiting:
            return  # boucle : laissée telle quelle, check_symbols la refusera
        visiting.add(key)
        for used in names_used(s.formula):
            if used in by_name and by_name[used] is not s:
                visit(by_name[used])
        visiting.discard(key)
        ordered.append(s)

    for s in symbols:
        visit(s)
    return ordered


def _gw_cards(deck: str) -> list[list[str]]:
    """Champs (après le code) de chaque carte GW du fichier, dans l'ordre."""
    out = []
    for line in deck.splitlines():
        if line.lstrip().startswith(("'", "!")):
            continue
        m = _CODE_RE.match(line)
        if m and m.group(1).upper() == "GW":
            out.append(split_fields(line[m.end() :]))
    return out


def keep_formulas(
    deck: str, codes: list[tuple[int, str]], wires: list[Wire]
) -> tuple[list[Symbol], list[Wire], str | None]:
    """Symboles et fils en formules, si le fichier s'y prête ; sinon ([], fils inchangés, raison).

    Tout ou rien : chaque carte GW, recalculée par onec avec les symboles relus ici, doit
    retomber sur un fil reconstruit (même tag, segments, extrémités à 50 µm, rayon). Ce
    recoupement protège aussi d'une mauvaise lecture des cartes SY.
    """
    from .symbols import check_symbols, formula_error, is_number, resolve

    symbols = parse_sy_cards(deck)
    if not symbols:
        return [], wires, None
    if transforms := sorted({c for _, c in codes} & TRANSFORM_CODES):
        return [], wires, f"le fichier copie ou déplace des fils ({', '.join(transforms)})"
    if issues := check_symbols(AntennaModel(symbols=symbols)):
        return [], wires, issues[0].message

    candidates: list[Wire] = []
    for fields in _gw_cards(deck):
        if len(fields) != 9 or not (fields[0].isdigit() and fields[1].isdigit()):
            return [], wires, "carte GW de forme inattendue"
        values: list[float | str] = []
        for f in fields[2:]:
            if is_number(f):
                values.append(float(f))
            elif formula_error(f) is None:
                values.append(f)
            else:
                return [], wires, f"formule « {f} » non reprise (unités ou notation 4NEC2)"
        candidates.append(
            Wire(int(fields[0]), int(fields[1]), tuple(values[:3]), tuple(values[3:6]), values[6])  # type: ignore[arg-type]
        )
    res = resolve(AntennaModel(wires=candidates, symbols=symbols))
    if res.model is None:
        return [], wires, res.issues[0].message if res.issues else "formules incalculables"

    out = list(wires)
    used: set[int] = set()
    for cand, num in zip(candidates, res.model.wires, strict=True):
        match = next(
            (
                i
                for i, w in enumerate(wires)
                if i not in used
                and w.tag == num.tag
                and w.segments == num.segments
                and math.dist(w.start, num.start) <= 5e-5  # type: ignore[arg-type]
                and math.dist(w.end, num.end) <= 5e-5  # type: ignore[arg-type]
                and math.isclose(w.radius, num.radius, rel_tol=1e-4)  # type: ignore[arg-type]
            ),
            None,
        )
        if match is None:
            return [], wires, f"le fil {cand.tag} ne se retrouve pas à l'identique"
        used.add(match)
        out[match] = cand
    return symbols, out, None


# --- Reconstruction du modèle -------------------------------------------------------------


def _round_point(p: tuple[float, float, float]) -> tuple[float, float, float]:
    # 10 µm : la précision imprimée par onec (5 décimales). Un arrondi plus grossier fausse les
    # petites antennes (UHF, hélices à l'échelle du mm) ; un fil posé au sol retombe à z = 0.
    return tuple(round(c, 5) + 0.0 for c in p)  # type: ignore[return-value]


def segments_to_wires(segments: list[Segment]) -> list[Wire]:
    """Regroupe les segments contigus, alignés, de même tag, rayon et longueur en un fil."""
    wires: list[Wire] = []
    run: list[Segment] = []
    points: list[tuple[float, float, float]] = []

    def snap(p: tuple[float, float, float]) -> tuple[float, float, float]:
        # Deux extrémités arrondies séparément peuvent différer de quelques 10 µm : pour NEC ce
        # seraient deux fils non connectés. On réutilise tout point déjà vu à moins de 50 µm.
        p = _round_point(p)
        for q in points:
            if math.dist(p, q) <= 5e-5:
                return q
        points.append(p)
        return p

    def flush() -> None:
        if not run:
            return
        if len(run) == 1:
            start, end = run[0].ends()
        else:
            # Longueur de segment déduite de l'écart entre le premier et le dernier centre :
            # bien plus précise que la longueur imprimée d'un seul segment (5 décimales).
            first, last = run[0].center, run[-1].center
            step = [(b - a) / (len(run) - 1) for a, b in zip(first, last, strict=True)]
            start = tuple(c - s / 2 for c, s in zip(first, step, strict=True))
            end = tuple(c + s / 2 for c, s in zip(last, step, strict=True))
        wires.append(Wire(run[0].tag, len(run), snap(start), snap(end), run[0].radius))  # type: ignore[arg-type]
        run.clear()

    for seg in segments:
        if run:
            last = run[-1]
            same_dir = sum(a * b for a, b in zip(last.direction(), seg.direction(), strict=True))
            gap = math.dist(last.ends()[1], seg.ends()[0])
            if (
                seg.tag == last.tag
                and seg.radius == last.radius
                and abs(seg.length - last.length) <= 2e-5
                and same_dir > 1 - 1e-6
                and gap <= 1e-4
            ):
                run.append(seg)
                continue
            flush()
        run.append(seg)
    flush()
    return wires


def _segment_in_tag(segments: list[Segment], absolute: int) -> tuple[int, int]:
    """Numéro absolu de segment → (tag, rang dans ce tag), comme NEC les numérote."""
    target = next((s for s in segments if s.number == absolute), None)
    if target is None:
        raise ImportRefused(f"source sur le segment {absolute}, qui n'existe pas")
    rank = sum(1 for s in segments if s.tag == target.tag and s.number <= absolute)
    return target.tag, rank


def _coded_lines(deck: str) -> list[tuple[tuple[int, str], str]]:
    out = []
    for n, line in enumerate(deck.splitlines(), start=1):
        m = _CODE_RE.match(line)
        if m and not line.lstrip().startswith(("'", "!")):
            out.append(((n, m.group(1).upper()), line[m.end() :].split("'", 1)[0]))
    return out


def _words(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z_]\w*", text)]


def import_deck(deck: str, filename: str = "") -> ImportResult:
    """Lit un fichier .nec et le traduit en modèle éditable (voir l'en-tête du module)."""
    if not deck.strip():
        raise ImportRefused("fichier vide")
    if len(deck.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ImportRefused(f"fichier trop gros (maximum {MAX_IMPORT_BYTES // 1000} ko)")

    # 1. Codes présents dans le fichier : refus, cartes écartées, cartes inconnues
    codes = card_codes(deck)
    for n, code in codes:
        if code in REFUSED_CODES:
            raise ImportRefused(f"non géré : {REFUSED_CODES[code]}, ligne {n}")
        known = GEOMETRY_CODES | HANDLED_CODES | set(DROPPED_CODES)
        if code not in known:
            raise ImportRefused(f"carte inconnue « {code} », ligne {n}")
    # Un seul calcul est représentable. Après le premier, d'autres fréquences (FR) sont
    # tolérées et ignorées (usage courant de 4NEC2) ; toute carte qui modifierait l'antenne
    # (LD, GN, EX…) ferait du second calcul un autre modèle : refus.
    executed = False
    fr_before_run = 0
    for n, code in codes:
        if code in EXECUTION_CODES:
            executed = True
        elif code == "FR" and not executed:
            fr_before_run += 1
        elif executed and code in COMMAND_CODES - {"FR"}:
            raise ImportRefused(
                f"non géré : plusieurs calculs enchaînés (carte {code} après un calcul), ligne {n}"
            )
    # FR en vigueur au premier calcul : NEC garde la dernière lue avant lui
    fr_used = max(fr_before_run - 1, 0)
    dropped_counts: dict[str, int] = {}
    for _, code in codes:
        if code in DROPPED_CODES:
            dropped_counts[code] = dropped_counts.get(code, 0) + 1

    # 2. Lecture par onec, sans calcul
    output = run_onec(strip_execution(deck), timeout=IMPORT_TIMEOUT_S)
    segments = parse_segments(output)
    if not segments:
        raise ModelRejected("onec n'a trouvé aucun fil dans ce fichier")
    cards = parse_data_cards(output)

    # 3. Cartes de commande
    notes: list[str] = []
    ground = Ground("free")
    excitation: Excitation | None = None
    sweep: FrequencySweep | None = None
    extra: list[ExtraCard] = []
    fr_seen = 0
    for card in cards:
        i1, i2, i3, _ = card.ints
        f1, f2, f3, f4, f5, f6 = card.floats
        if card.code == "GN":
            if i2 != 0 or any((f3, f4, f5, f6)):
                raise ImportRefused("non géré : sol avec écran de radians ou second milieu (GN)")
            if i1 == -1:
                ground = Ground("free")
            elif i1 == 1:
                ground = Ground("perfect")
            elif i1 in (0, 2):
                ground = Ground("real", epsilon_r=f1, conductivity=f2, exact=i1 == 2)
            else:
                raise ImportRefused(f"type de sol GN {i1} non géré")
        elif card.code == "FR":
            fr_seen += 1
            if fr_seen - 1 != fr_used:
                if fr_seen == 2 or (fr_used and fr_seen == 1):
                    notes.append(
                        "plusieurs fréquences (FR) : seule celle du premier calcul est reprise"
                    )
                continue
            count = max(i2, 1)
            if i1 == 1 and count > 1:  # balayage multiplicatif → linéaire sur la même plage
                end = f1 * f2 ** (count - 1)
                sweep = FrequencySweep(f1, (end - f1) / (count - 1), count)
                notes.append("balayage multiplicatif remplacé par un balayage linéaire")
            else:
                sweep = FrequencySweep(f1, f2, count)
        elif card.code == "EX" and excitation is None and i1 in (0, 5):
            tag, seg = (i2, i3) if i2 != 0 else _segment_in_tag(segments, i3)
            excitation = Excitation(tag, seg, f1, f2, kind=i1)
        elif card.code in KEPT_CODES:
            extra.append(ExtraCard(card.text(), describe_card(card)))
        # les autres cartes recopiées par onec (RP, PT…) ont été retirées avant lecture

    if excitation is None:
        raise ImportRefused(
            "aucune source de tension (EX 0 ou EX 5) : le point d'alimentation est requis"
        )
    if sweep is None:
        sweep = FrequencySweep(NEC_DEFAULT_MHZ)
        notes.append("aucune fréquence (FR) dans le fichier : 299,8 MHz, valeur par défaut de NEC")

    wires = segments_to_wires(segments)
    symbols: list[Symbol] = []
    if any(c[1] == "SY" for c in codes):
        symbols, wires, reason = keep_formulas(deck, codes, wires)
        if reason:
            notes.append(f"symboles (SY) remplacés par leurs valeurs : {reason}")
        else:
            if any(c[1] in ("GA", "GH") for c in codes):
                notes.append("arcs et hélices (GA, GH) repris en valeurs : sans formules")
            names = {s.name.lower() for s in symbols}
            if any(
                c[1] not in GEOMETRY_CODES and names & set(_words(line))
                for c, line in _coded_lines(deck)
            ):
                notes.append(
                    "les cartes LD, EX, FR… gardent les valeurs calculées à l'import : "
                    "changer un symbole ne les modifie pas"
                )
    if any(e.text.split()[0] in ("LD", "TL", "NT") for e in extra):
        notes.append(
            "modifier le nombre de segments d'un fil peut décaler les cartes conservées qui y "
            "font référence"
        )

    comment = f"Importe de {filename}" if filename else "Importe par Open2Nec"
    model = AntennaModel(
        wires=wires,
        symbols=symbols,
        excitations=[excitation],
        ground=ground,
        sweep=sweep,
        comment=comment,
        extra_cards=[e.text for e in extra],
    )
    freqs = sweep.frequencies
    return ImportResult(
        model=model,
        frequency_mhz=round((freqs[0] + freqs[-1]) / 2, 6),
        extra=extra,
        dropped=[
            f"{DROPPED_CODES[c]} ×{n}" if n > 1 else DROPPED_CODES[c]
            for c, n in dropped_counts.items()
        ],
        notes=notes,
    )
