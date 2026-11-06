"""Optimiseur : fait varier des symboles pour minimiser un score pondéré (façon 4NEC2).

Tous les critères sont en dB, pour que les poids se comparent :
  - ROS : perte de désadaptation au pire point de la bande, −10·log10(1 − |Γ|²)
    (0 dB à ROS 1 ; 0,512 dB à ROS 2) ;
  - gain : gain moyen sur la bande dans la direction (θ, φ), à maximiser ;
  - AV/AR : rapport avant/arrière au pire point de la bande, plafonné (30 dB par défaut) — sans
    plafond, la recherche courrait après un zéro très étroit à une seule fréquence.
score = Σ poids × critère / Σ poids (le gain et l'AV/AR comptés négativement), à minimiser.

Algorithme : Nelder-Mead borné (SciPy), sur des variables ramenées à [0, 1]. Recherche locale :
elle affine un modèle de départ déjà proche. Un essai refusé (contrôle du modèle ou onec) reçoit
une forte pénalité et la recherche continue. Pas de thread ici : l'appelant reçoit chaque essai
par `on_progress` et peut arrêter par `should_stop`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from .engine import EngineError
from .model import AntennaModel, FrequencySweep
from .sweep import simulate_sweep, swr_from_gamma
from .symbols import as_value, validate_with_symbols, with_values

PENALTY = 1000.0  # score d'un essai refusé
MAX_SWR_LOSS_DB = 60.0  # perte de désadaptation retenue pour un ROS infini
DEFAULT_MAX_EVALUATIONS = 300


class OptimizerUnavailable(RuntimeError):
    """SciPy absent : pip install open2nec[optim]."""


@dataclass
class Variable:
    """Symbole à faire varier entre deux bornes."""

    name: str
    low: float
    high: float


@dataclass
class Objective:
    band_low_mhz: float
    band_high_mhz: float
    n_points: int = 3
    z0: float = 50.0
    direction: tuple[float, float] | None = None  # (θ, φ) en degrés, pour gain et AV/AR
    w_swr: float = 100.0  # poids en %
    w_gain: float = 0.0
    w_fb: float = 0.0
    fb_cap_db: float = 30.0

    @property
    def frequencies(self) -> FrequencySweep:
        if self.n_points <= 1 or self.band_high_mhz == self.band_low_mhz:
            return FrequencySweep(round((self.band_low_mhz + self.band_high_mhz) / 2, 9))
        step = (self.band_high_mhz - self.band_low_mhz) / (self.n_points - 1)
        return FrequencySweep(self.band_low_mhz, step, self.n_points)


@dataclass
class Criteria:
    swr_max: float  # pire ROS de la bande (math.inf possible)
    swr_loss_db: float  # perte de désadaptation correspondante
    gain_db: float | None = None  # gain moyen dans la direction
    fb_db: float | None = None  # pire AV/AR de la bande (non plafonné)


@dataclass
class Trial:
    n: int  # 0 = modèle de départ
    values: dict[str, float]
    score: float
    criteria: Criteria | None = None
    error: str | None = None  # raison du refus


@dataclass
class OptimizeResult:
    start: Trial
    best: Trial
    evaluations: int
    reason: str  # "converged", "max_evaluations" ou "stopped"
    trials: list[Trial] = field(default_factory=list)


def mismatch_loss_db(swr: float) -> float:
    """Perte de désadaptation (dB) pour un ROS : −10·log10(1 − |Γ|²)."""
    if math.isinf(swr):
        return MAX_SWR_LOSS_DB
    g = (swr - 1) / (swr + 1)
    return min(-10 * math.log10(1 - g * g), MAX_SWR_LOSS_DB)


def score_of(c: Criteria, obj: Objective) -> float:
    total = obj.w_swr + obj.w_gain + obj.w_fb
    s = obj.w_swr * c.swr_loss_db
    if obj.w_gain:
        s -= obj.w_gain * (c.gain_db if c.gain_db is not None else -PENALTY)
    if obj.w_fb:
        fb = c.fb_db if c.fb_db is not None else -PENALTY
        s -= obj.w_fb * min(fb, obj.fb_cap_db)
    return s / total


def check_setup(model: AntennaModel, variables: list[Variable], obj: Objective) -> None:
    """Lève ValueError (message en français) si la demande n'a pas de sens."""
    if not variables:
        raise ValueError("aucune variable à optimiser")
    by_name = {s.name.lower(): s for s in model.symbols}
    seen: set[str] = set()
    for v in variables:
        sym = by_name.get(v.name.lower())
        if sym is None:
            raise ValueError(f"variable « {v.name} » : ce symbole n'existe pas")
        if v.name.lower() in seen:
            raise ValueError(f"variable « {v.name} » citée deux fois")
        seen.add(v.name.lower())
        value = as_value(sym.formula)
        if isinstance(value, str):  # saisie de l'utilisateur, pas une erreur de programmation
            raise ValueError(  # noqa: TRY004
                f"variable « {v.name} » : seul un symbole qui vaut un nombre peut varier "
                f"(ici « {sym.formula} »)"
            )
        if not (math.isfinite(v.low) and math.isfinite(v.high) and v.low < v.high):
            raise ValueError(f"variable « {v.name} » : bornes invalides")
        if not v.low <= value <= v.high:
            raise ValueError(
                f"variable « {v.name} » : la valeur de départ {value:g} est hors des bornes"
            )
    if obj.w_swr < 0 or obj.w_gain < 0 or obj.w_fb < 0 or obj.w_swr + obj.w_gain + obj.w_fb <= 0:
        raise ValueError("poids : positifs, et au moins un non nul")
    if (obj.w_gain or obj.w_fb) and obj.direction is None:
        raise ValueError("gain et AV/AR demandent une direction (θ, φ)")
    if not 0 < obj.band_low_mhz <= obj.band_high_mhz:
        raise ValueError("bande de fréquences invalide")
    if obj.z0 <= 0:
        raise ValueError("z0 doit être > 0")


def evaluate(model: AntennaModel, values: dict[str, float], obj: Objective, n: int) -> Trial:
    """Un essai : symboles remplacés, contrôle du modèle, balayage sur les points de la bande."""
    trial_model = replace(with_values(model, values), sweep=obj.frequencies, pattern=None)
    try:
        _, issues = validate_with_symbols(trial_model, obj.band_high_mhz)
        errors = [i.message for i in issues if i.severity == "error"]
        if errors:
            return Trial(n, values, PENALTY, error=errors[0])
        _, points, _ = simulate_sweep(trial_model, obj.z0, obj.direction)
    except EngineError as exc:  # ModelRejected compris
        return Trial(n, values, PENALTY, error=str(exc))
    if not points:
        return Trial(n, values, PENALTY, error="aucun résultat")
    swr_max = max(swr_from_gamma(p.gamma) for p in points)
    c = Criteria(swr_max, mismatch_loss_db(swr_max))
    if obj.direction is not None:
        gains = [p.gain_db for p in points]
        fbs = [p.front_to_back_db for p in points]
        c.gain_db = sum(gains) / len(gains) if None not in gains else None  # type: ignore[arg-type]
        c.fb_db = min(fbs) if None not in fbs else None  # type: ignore[type-var]
    return Trial(n, values, score_of(c, obj), criteria=c)


class _Stop(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def optimize(
    model: AntennaModel,
    variables: list[Variable],
    objective: Objective,
    max_evaluations: int = DEFAULT_MAX_EVALUATIONS,
    on_progress: Callable[[Trial, Trial], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    keep_trials: bool = False,
) -> OptimizeResult:
    """Cherche les valeurs des variables qui minimisent le score (voir l'en-tête du module).

    `on_progress(essai, meilleur)` est appelé après chaque calcul. Le résultat contient le
    meilleur essai trouvé, même après un arrêt demandé ; le modèle n'est jamais modifié.
    """
    try:
        import numpy as np
        from scipy.optimize import minimize
    except ImportError as exc:
        raise OptimizerUnavailable(
            "optimiseur indisponible : installer SciPy (pip install open2nec[optim])"
        ) from exc

    check_setup(model, variables, objective)
    by_name = {s.name.lower(): s for s in model.symbols}
    x_start = [float(as_value(by_name[v.name.lower()].formula)) for v in variables]
    span = [v.high - v.low for v in variables]

    def to_values(u) -> dict[str, float]:  # [0, 1]ⁿ → valeurs physiques
        return {
            v.name: v.low + min(1.0, max(0.0, float(ui))) * s
            for v, ui, s in zip(variables, u, span, strict=True)
        }

    trials: list[Trial] = []
    cache: dict[tuple[float, ...], float] = {}
    state: dict[str, Trial] = {}

    def run(values: dict[str, float], first: bool = False) -> Trial:
        # L'essai de départ est toujours calculé (il sert de référence « avant ») ; un arrêt
        # demandé pendant le chargement de SciPy prend effet juste après lui.
        if should_stop and should_stop() and not first:
            raise _Stop("stopped")
        if len(trials) >= max_evaluations:
            raise _Stop("max_evaluations")
        trial = evaluate(model, values, objective, len(trials))
        trials.append(trial)
        if "best" not in state or trial.score < state["best"].score:
            state["best"] = trial
        if on_progress:
            on_progress(trial, state["best"])
        return trial

    def fun(u) -> float:
        values = to_values(u)
        key = tuple(round(x, 12) for x in values.values())
        if key not in cache:  # Nelder-Mead repasse parfois par un même point
            cache[key] = run(values).score
        return cache[key]

    u0 = np.array([(x - v.low) / s for x, v, s in zip(x_start, variables, span, strict=True)])
    # Simplexe de départ : 10 % de la plage sur chaque axe, vers l'intérieur des bornes
    simplex = [u0]
    for i in range(len(variables)):
        p = u0.copy()
        p[i] = p[i] + 0.1 if p[i] + 0.1 <= 1 else p[i] - 0.1
        simplex.append(p)

    start = run(dict(zip((v.name for v in variables), x_start, strict=True)), first=True)
    cache[tuple(round(x, 12) for x in x_start)] = start.score
    # Gain ou AV/AR demandés mais absents au départ (direction sans rayonnement, par exemple
    # l'horizon au-dessus du sol) : tous les essais vaudraient la même pénalité, recherche inutile.
    c = start.criteria
    if c is not None and objective.direction is not None:
        theta, phi = objective.direction
        if (objective.w_gain and c.gain_db is None) or (objective.w_fb and c.fb_db is None):
            raise ValueError(
                f"aucun rayonnement dans la direction θ = {theta:g}°, φ = {phi:g}° (ou à "
                "l'opposé) : gain et AV/AR n'y ont pas de sens. Au-dessus du sol, viser une "
                "élévation (θ < 90°), par exemple celle du maximum du diagramme."
            )
    reason = "converged"
    try:
        minimize(
            fun,
            u0,
            method="Nelder-Mead",
            bounds=[(0.0, 1.0)] * len(variables),
            options={
                "initial_simplex": np.array(simplex),
                "xatol": 1e-4,  # 0,01 % de la plage
                "fatol": 1e-3,  # 0,001 dB
                "maxfev": max_evaluations * 2,  # la limite réelle est tenue par run()
            },
        )
    except _Stop as stop:
        reason = stop.reason
    return OptimizeResult(
        start=start,
        best=state["best"],
        evaluations=len(trials),
        reason=reason,
        trials=trials if keep_trials else [],
    )


__all__ = [
    "Criteria",
    "Objective",
    "OptimizeResult",
    "OptimizerUnavailable",
    "Trial",
    "Variable",
    "evaluate",
    "mismatch_loss_db",
    "optimize",
    "score_of",
]
