"""Contrôle d'un modèle avant calcul : erreurs bloquantes, avertissements, conseils.

Règles usuelles de modélisation NEC-2 (manuel NEC-2, recommandations reprises par 4NEC2) :
segments entre 0,001 λ et λ/10, segment ≥ 8 × rayon (hypothèse du fil mince), jonctions aux
extrémités de segments seulement, segments voisins de longueurs et rayons comparables, fils
parallèles proches segmentés de façon alignée, source loin d'un bout de fil libre.

`onec -t` n'est pas utilisé : en pratique il ne signale qu'une petite partie de ces cas.
Les fils sont désignés par leur rang dans `model.wires` (= ligne du tableau de l'interface).
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from ..cards import parse_card
from ..model import AntennaModel, Wire

C_MHZ_M = 299.792458  # c en m·MHz
MAX_PAIRWISE_WIRES = 500  # au-delà, les contrôles entre paires de fils sont trop lents

Severity = Literal["error", "warning", "info"]
Vec = tuple[float, float, float]


@dataclass
class Issue:
    severity: Severity
    code: str
    message: str
    wires: tuple[int, ...] = field(default=())  # rangs dans model.wires
    symbols: tuple[int, ...] = field(default=())  # rangs dans model.symbols


# --- Géométrie élémentaire ------------------------------------------------------------------


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _lerp(a: Vec, b: Vec, t: float) -> Vec:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _point_segment(p: Vec, a: Vec, b: Vec) -> tuple[float, float]:
    """(distance de p au segment [a, b], position t ∈ [0, 1] du point le plus proche)."""
    ab = _sub(b, a)
    den = _dot(ab, ab)
    t = 0.0 if den == 0 else min(1.0, max(0.0, _dot(_sub(p, a), ab) / den))
    return math.dist(p, _lerp(a, b, t)), t


def _segment_segment(a1: Vec, b1: Vec, a2: Vec, b2: Vec) -> tuple[float, float, float]:
    """Distance minimale entre deux segments et positions (s, t) des points les plus proches."""
    d1, d2, r = _sub(b1, a1), _sub(b2, a2), _sub(a1, a2)
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    c, b = _dot(d1, r), _dot(d1, d2)
    den = a * e - b * b
    s = min(1.0, max(0.0, (b * f - c * e) / den)) if den > 1e-15 else 0.0
    t = (b * s + f) / e if e > 0 else 0.0
    if t < 0:
        t, s = 0.0, min(1.0, max(0.0, -c / a)) if a > 0 else 0.0
    elif t > 1:
        t, s = 1.0, min(1.0, max(0.0, (b - c) / a)) if a > 0 else 0.0
    return math.dist(_lerp(a1, b1, s), _lerp(a2, b2, t)), s, t


@dataclass
class _W:
    """Fil prétraité pour les contrôles."""

    index: int
    wire: Wire
    a: Vec
    b: Vec
    length: float
    seg: float  # longueur d'un segment
    unit: Vec

    @property
    def label(self) -> str:
        return f"ligne {self.index + 1} (tag {self.wire.tag})"

    def boundaries(self) -> Iterator[Vec]:
        n = self.wire.segments
        for k in range(n + 1):
            yield _lerp(self.a, self.b, k / n)


def _prepare(wires: list[Wire]) -> list[_W]:
    out = []
    for i, w in enumerate(wires):
        a, b = tuple(map(float, w.start)), tuple(map(float, w.end))
        length = math.dist(a, b)
        if length == 0 or w.segments < 1:
            continue  # fil dégénéré : refusé en amont (saisie / API)
        d = _sub(b, a)
        out.append(
            _W(
                i,
                w,
                a,
                b,
                length,
                length / w.segments,
                (d[0] / length, d[1] / length, d[2] / length),
            )
        )  # type: ignore[arg-type]
    return out


def _tol(*ws: _W) -> float:
    """Tolérance de jonction : 1/1000 du plus court segment concerné (ordre de grandeur NEC)."""
    return max(1e-6, 1e-3 * min(w.seg for w in ws))


# --- Contrôles -------------------------------------------------------------------------------


def check_excitations(model: AntennaModel) -> list[str]:
    """Erreurs bloquantes sur les excitations (le modèle ne doit pas être simulé).

    - au moins une excitation, sinon aucune impédance n'est calculée ;
    - le fil désigné (tag) doit exister ;
    - le segment doit exister sur ce fil (1 à nombre de segments).
    """
    if not model.excitations:
        return ["aucune excitation : ajouter une source sur un segment"]
    by_tag = _segments_by_tag(model.wires)
    errors: list[str] = []
    for e in model.excitations:
        n = by_tag.get(e.tag)
        if n is None:
            errors.append(f"excitation sur le fil {e.tag} : ce fil n'existe pas")
        elif not 1 <= e.segment <= n:
            errors.append(
                f"excitation sur le fil {e.tag} : segment {e.segment} hors limites (1 à {n})"
            )
    return errors


def _segments_by_tag(wires: list[Wire]) -> dict[int, int]:
    # plusieurs fils de même tag (arc importé découpé en fils droits…) : NEC numérote leurs
    # segments à la suite, de 1 au total
    out: dict[int, int] = {}
    for w in wires:
        out[w.tag] = out.get(w.tag, 0) + w.segments
    return out


def _excitation_issues(model: AntennaModel) -> list[Issue]:
    """check_excitations sous forme de remarques, rattachées aux fils du tag visé."""
    if not model.excitations:
        return [Issue("error", "excitation", check_excitations(model)[0])]
    issues = []
    for e in model.excitations:
        single = AntennaModel(wires=model.wires, excitations=[e])
        issues += [
            Issue("error", "excitation", msg, _rows_of_tag(model, e.tag))
            for msg in check_excitations(single)
        ]
    return issues


def _rows_of_tag(model: AntennaModel, tag: int) -> tuple[int, ...]:
    return tuple(i for i, w in enumerate(model.wires) if w.tag == tag)


def _check_extra_cards(model: AntennaModel) -> list[Issue]:
    """Cartes conservées qui visent un fil ou un segment absent (après modification)."""
    by_tag = _segments_by_tag(model.wires)
    total = sum(by_tag.values())
    issues: list[Issue] = []

    def bad(tag: int, seg: int) -> str | None:
        if tag == 0:  # numérotation globale des segments
            return (
                None if 1 <= seg <= total else f"segment {seg} (numérotation globale, 1 à {total})"
            )
        if tag not in by_tag:
            return f"fil de tag {tag}, absent du modèle"
        if seg != 0 and not 1 <= seg <= by_tag[tag]:
            return f"segment {seg} du fil {tag} (1 à {by_tag[tag]})"
        return None

    for text in model.extra_cards:
        card = parse_card(text)
        i1, i2, i3, i4 = card.ints
        refs: list[tuple[int, int]] = []
        if card.code == "LD":
            if not (i2 == 0 and i3 == 0 and i4 == 0):  # LD n 0 0 0 = tous les segments
                refs = [(i2, i3), (i2, i4)] if i2 else [(0, i3), (0, i4)]
        elif card.code in ("TL", "NT"):
            refs = [(i1, i2), (i3, i4)]
        elif card.code == "EX":
            refs = [(i2, i3)]
        problems = [p for t, s in refs if (p := bad(t, s))]
        if problems:
            issues.append(
                Issue(
                    "error",
                    "extra_card",
                    f"carte conservée « {text} » : {problems[0]}. Le modèle a changé depuis "
                    "l'import ; rétablir le fil ou ses segments.",
                    tuple(sorted({r for t, _ in refs if t for r in _rows_of_tag(model, t)})),
                )
            )
    return issues


def _check_ground(model: AntennaModel, ws: list[_W], wavelength: float) -> list[Issue]:
    if model.ground.kind == "free":
        return []
    issues: list[Issue] = []
    low: list[int] = []
    for w in ws:
        tol = _tol(w)
        za, zb = w.a[2], w.b[2]
        if min(za, zb) < -tol:
            issues.append(
                Issue(
                    "error", "ground_below", f"{w.label} : passe sous le sol (z < 0).", (w.index,)
                )
            )
        elif abs(za) <= tol and abs(zb) <= tol:
            issues.append(
                Issue(
                    "error",
                    "ground_flat",
                    f"{w.label} : posé à plat sur le sol (z = 0) ; onec refuse ce cas. "
                    "Le surélever (quelques cm suffisent) ou n'y poser qu'une extrémité.",
                    (w.index,),
                )
            )
        elif min(za, zb) < 0.1 * wavelength:
            low.append(w.index)
    if low and model.ground.kind == "real" and not model.ground.exact:
        issues.append(
            Issue(
                "info",
                "ground_approx",
                f"{len(low)} fil(s) à moins de 0,1 λ du sol avec le sol approché (GN 0) : "
                "cocher « calcul exact » (Sommerfeld) pour un résultat fiable.",
                tuple(low),
            )
        )
    return issues


def _check_segments(ws: list[_W], wavelength: float) -> list[Issue]:
    issues: list[Issue] = []
    for w in ws:
        frac = w.seg / wavelength
        if frac > 0.2:
            issues.append(
                Issue(
                    "warning",
                    "segment_long",
                    f"{w.label} : segments de {w.seg:.3g} m ({frac:.2f} λ), bien au-delà de λ/10 ; augmenter le nombre de segments.",
                    (w.index,),
                )
            )
        elif frac > 0.1:
            issues.append(
                Issue(
                    "warning",
                    "segment_long",
                    f"{w.label} : segments de {w.seg:.3g} m ({frac:.2f} λ) > λ/10 ; augmenter le nombre de segments.",
                    (w.index,),
                )
            )
        elif frac < 1e-3:
            issues.append(
                Issue(
                    "warning",
                    "segment_short",
                    f"{w.label} : segments de {w.seg:.3g} m ({frac:.1e} λ) < 0,001 λ ; précision numérique douteuse, réduire le nombre de segments.",
                    (w.index,),
                )
            )
        r = w.wire.radius
        # Fil mince (manuel NEC-2) : exact au-delà d'un rapport segment/rayon de 8, erreur
        # croissante entre 8 et 2, approximation fausse en dessous de 2
        ratio = w.seg / r
        if ratio < 2:
            issues.append(
                Issue(
                    "warning",
                    "thin_wire",
                    f"{w.label} : segment de {w.seg:.3g} m pour un rayon de {r:.3g} m (rapport "
                    f"{ratio:.1f} < 2) ; l'hypothèse du fil mince n'est plus valable : moins de "
                    "segments ou fil plus fin.",
                    (w.index,),
                )
            )
        elif ratio < 8:
            issues.append(
                Issue(
                    "info",
                    "thin_wire_marginal",
                    f"{w.label} : rapport segment/rayon de {ratio:.1f} (< 8) ; précision un peu "
                    "réduite, acceptable en général.",
                    (w.index,),
                )
            )
    return issues


def check_segmentation(model: AntennaModel) -> list[Issue]:
    """Contrôles de segmentation seuls (longueur vs λ, rapport segment/rayon)."""
    fmax = max(model.sweep.frequencies)
    return _check_segments(_prepare(model.wires), C_MHZ_M / fmax)


def _end_is_connected(p: Vec, me: _W, ws: list[_W], grounded: bool) -> bool:
    """Une extrémité est reliée si elle touche une extrémité d'un autre fil ou le sol."""
    if grounded and abs(p[2]) <= _tol(me):
        return True
    for o in ws:
        if o is me:
            continue
        tol = _tol(me, o)
        if math.dist(p, o.a) <= tol or math.dist(p, o.b) <= tol:
            return True
    return False


def _check_feed(model: AntennaModel, ws: list[_W], wavelength: float) -> list[Issue]:
    if not model.excitations:
        return []
    ex = model.excitations[0]
    rows = [w for w in ws if w.wire.tag == ex.tag]
    remaining = ex.segment
    for w in rows:  # segment n du tag → fil et rang dans ce fil
        if remaining > w.wire.segments:
            remaining -= w.wire.segments
            continue
        k, n = remaining - 1, w.wire.segments
        issues: list[Issue] = []
        grounded = model.ground.kind != "free"
        ends = ([w.a] if k == 0 else []) + ([w.b] if k == n - 1 else [])
        if any(not _end_is_connected(p, w, ws, grounded) for p in ends):
            issues.append(
                Issue(
                    "warning",
                    "feed_free_end",
                    f"{w.label} : source sur le segment {ex.segment}, en bout de fil libre ; le "
                    "courant y est quasi nul et l'impédance sans signification. Alimenter un "
                    "segment intérieur.",
                    (w.index,),
                )
            )
        if len(rows) == 1 and n % 2 == 0 and ex.segment in (n // 2, n // 2 + 1):
            issues.append(
                Issue(
                    "info",
                    "feed_even",
                    f"{w.label} : nombre de segments pair ({n}) ; la source n'est pas au centre exact du fil. Prendre un nombre impair.",
                    (w.index,),
                )
            )
        if w.seg > wavelength / 20:
            issues.append(
                Issue(
                    "info",
                    "feed_coarse",
                    f"{w.label} : segment alimenté de {w.seg / wavelength:.3f} λ ; près de la source, viser < λ/20 pour une impédance précise.",
                    (w.index,),
                )
            )
        return issues
    return []  # source hors limites : signalée par check_excitations


def _check_pairs(ws: list[_W], wavelength: float) -> list[Issue]:
    issues: list[Issue] = []
    for i, p in enumerate(ws):
        for q in ws[i + 1 :]:
            reach = max(p.wire.radius, q.wire.radius) + 0.05 * wavelength
            if any(  # préfiltre : boîtes englobantes éloignées
                min(p.a[k], p.b[k]) - reach > max(q.a[k], q.b[k])
                or min(q.a[k], q.b[k]) - reach > max(p.a[k], p.b[k])
                for k in range(3)
            ):
                continue
            issues += _check_pair(p, q, wavelength)
    return issues


def _check_pair(p: _W, q: _W, wavelength: float) -> list[Issue]:
    tol = _tol(p, q)
    both = (p.index, q.index)
    names = f"{p.label} et {q.label}"
    same = lambda u, v: math.dist(u, v) <= tol

    if (same(p.a, q.a) and same(p.b, q.b)) or (same(p.a, q.b) and same(p.b, q.a)):
        return [
            Issue(
                "error",
                "overlap",
                f"{names} : fils superposés (mêmes extrémités) ; en supprimer un.",
                both,
            )
        ]

    issues: list[Issue] = []
    joined = [(u, v) for u in (p.a, p.b) for v in (q.a, q.b) if same(u, v)]
    if joined:  # jonction bout à bout : segments et rayons voisins comparables
        ratio = max(p.seg, q.seg) / min(p.seg, q.seg)
        if ratio > 5:
            issues.append(
                Issue(
                    "warning",
                    "junction_segments",
                    f"{names} : jonction entre segments de {p.seg:.3g} m et {q.seg:.3g} m (rapport {ratio:.1f}:1) ; viser moins de 2:1.",
                    both,
                )
            )
        rr = max(p.wire.radius, q.wire.radius) / min(p.wire.radius, q.wire.radius)
        if rr > 5:
            issues.append(
                Issue(
                    "warning",
                    "junction_radius",
                    f"{names} : jonction entre rayons de {p.wire.radius:.3g} m et {q.wire.radius:.3g} m (rapport {rr:.0f}:1) ; résultat moins précis.",
                    both,
                )
            )

    # extrémité d'un fil posée sur l'intérieur d'un autre, hors limite de segment
    for me, other in ((p, q), (q, p)):
        for end in (me.a, me.b):
            d, t = _point_segment(end, other.a, other.b)
            if (
                d > max(tol, other.wire.radius)
                or t * other.length <= tol
                or (1 - t) * other.length <= tol
            ):
                continue
            if not any(same(end, bnd) for bnd in other.boundaries()):
                issues.append(
                    Issue(
                        "warning",
                        "mid_segment",
                        f"{me.label} aboutit au milieu d'un segment de {other.label} : NEC ne relie "
                        "les fils qu'aux limites de segments, ces fils ne sont donc PAS connectés. "
                        "Couper l'autre fil à cet endroit ou ajuster sa segmentation.",
                        both,
                    )
                )
    if joined or any(i.code == "mid_segment" for i in issues):
        return issues

    parallel = abs(_dot(p.unit, q.unit)) > 0.9999
    d, s, t = _segment_segment(p.a, p.b, q.a, q.b)
    if parallel:
        # distance entre axes et recouvrement des projections
        dist_axes = _line_distance(p, q)
        lo, hi = sorted((_dot(_sub(q.a, p.a), p.unit), _dot(_sub(q.b, p.a), p.unit)))
        overlap = min(hi, p.length) - max(lo, 0.0)
        if dist_axes < 0.05 * wavelength and overlap > tol:
            if dist_axes <= p.wire.radius + q.wire.radius:
                issues.append(
                    Issue(
                        "error",
                        "overlap",
                        f"{names} : fils parallèles qui se recouvrent ; en supprimer un ou les écarter.",
                        both,
                    )
                )
            elif not _aligned(p, q):
                issues.append(
                    Issue(
                        "warning",
                        "parallel_misaligned",
                        f"{names} : fils parallèles proches ({dist_axes:.3g} m, {dist_axes / wavelength:.3f} λ) "
                        "aux segments non alignés ; donner aux deux la même longueur de segment, "
                        "limites en face l'une de l'autre.",
                        both,
                    )
                )
        return issues

    # NEC relie les segments par leurs extrémités, où qu'elles soient le long des fils : un
    # croisement exactement sur une limite de segment de chacun est une vraie jonction.
    on_boundary = lambda w, x: abs(x * w.wire.segments - round(x * w.wire.segments)) * w.seg <= tol
    connected = on_boundary(p, s) and on_boundary(q, t)
    if d <= p.wire.radius + q.wire.radius and 0 < s < 1 and 0 < t < 1 and not connected:
        issues.append(
            Issue(
                "warning",
                "crossing",
                f"{names} : les fils se croisent sans être connectés ; NEC les traite comme séparés.",
                both,
            )
        )
    return issues


def _line_distance(p: _W, q: _W) -> float:
    """Distance entre deux droites parallèles (axes des fils)."""
    v = _sub(q.a, p.a)
    along = _dot(v, p.unit)
    perp = (v[0] - along * p.unit[0], v[1] - along * p.unit[1], v[2] - along * p.unit[2])
    return math.sqrt(_dot(perp, perp))


def _aligned(p: _W, q: _W) -> bool:
    """Segments de même longueur (±10 %) dont les limites se font face (à ¼ de segment près)."""
    if abs(p.seg - q.seg) > 0.1 * min(p.seg, q.seg):
        return False
    offset = _dot(_sub(q.a, p.a), p.unit) % p.seg
    return min(offset, p.seg - offset) <= 0.25 * p.seg


def validate_model(model: AntennaModel, max_frequency_mhz: float | None = None) -> list[Issue]:
    """Toutes les remarques sur le modèle, les erreurs d'abord.

    `max_frequency_mhz` : fréquence la plus haute utilisée (balayage ou diagramme) ; par défaut
    celle du balayage du modèle.
    """
    fmax = max_frequency_mhz or max(model.sweep.frequencies)
    wavelength = C_MHZ_M / fmax
    ws = _prepare(model.wires)
    issues = _excitation_issues(model)
    issues += _check_extra_cards(model)
    issues += _check_ground(model, ws, wavelength)
    issues += _check_segments(ws, wavelength)
    issues += _check_feed(model, ws, wavelength)
    if len(ws) <= MAX_PAIRWISE_WIRES:
        issues += _check_pairs(ws, wavelength)
    else:
        issues.append(
            Issue(
                "info",
                "pairs_skipped",
                f"{len(ws)} fils : contrôles entre fils (jonctions, croisements, fils parallèles) non faits au-delà de {MAX_PAIRWISE_WIRES}.",
            )
        )
    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(_group(issues), key=lambda i: order[i.severity])


GROUP_ABOVE = 3  # au-delà, les remarques identiques sont regroupées


def _group(issues: list[Issue]) -> list[Issue]:
    """Regroupe les remarques de même code et gravité quand elles sont nombreuses : on garde
    la première en détail et on surligne tous les fils concernés."""
    by_key: dict[tuple[str, str], list[Issue]] = {}
    for i in issues:
        by_key.setdefault((i.severity, i.code), []).append(i)
    out: list[Issue] = []
    for (severity, code), group in by_key.items():
        if len(group) <= GROUP_ABOVE or severity == "error":
            out += group
            continue
        wires = tuple(sorted({w for i in group for w in i.wires}))
        first = group[0].message.rstrip(".")
        out.append(
            Issue(severity, code, f"{first} — et {len(group) - 1} autres cas semblables.", wires)
        )
    return out
