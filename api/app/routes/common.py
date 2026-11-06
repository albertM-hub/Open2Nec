"""Outils partagés par les routes : conversion vers le core, contrôles, erreurs HTTP."""

import math
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException

from open2nec import AntennaModel, Excitation, Ground, Symbol, Wire
from open2nec.engine import EngineError, ModelRejected
from open2nec.model import FrequencySweep
from open2nec.results import FeedpointResult
from open2nec.symbols import Resolved, validate_with_symbols
from open2nec.validate import Issue

from ..schemas import (
    ExcitationIn,
    FeedpointOut,
    GeometryIn,
    GroundIn,
    IssueOut,
    ModelIn,
    SweepIn,
    SymbolIn,
    WireIn,
)

# Délai maximal d'un calcul lancé depuis l'API (le core accepte plus en ligne de commande)
SIMULATION_TIMEOUT_S = 60.0


def geometry_to_core(g: GeometryIn) -> AntennaModel:
    """Fils, sources et sol ; le balayage et la grille sont ajoutés par l'appelant."""
    return AntennaModel(
        wires=[Wire(w.tag, w.segments, w.start, w.end, w.radius) for w in g.wires],
        symbols=[Symbol(s.name, s.formula) for s in g.symbols],
        excitations=[
            Excitation(e.tag, e.segment, e.voltage_re, e.voltage_im, kind=e.kind)
            for e in g.excitations
        ],
        ground=Ground(
            g.ground.kind, g.ground.epsilon_r, g.ground.conductivity, exact=g.ground.exact
        ),
        extra_cards=list(g.extra_cards),
    )


def model_to_core(m: ModelIn) -> AntennaModel:
    """Modèle complet (géométrie + balayage), sans grille de diagramme."""
    model = geometry_to_core(m)
    model.sweep = FrequencySweep(m.sweep.start_mhz, m.sweep.step_mhz, m.sweep.count)
    return model


def model_to_in(m: AntennaModel) -> ModelIn:
    """Modèle du core → JSON de l'API (modèles pré-remplis, fichiers importés)."""
    return ModelIn(
        wires=[
            WireIn(tag=w.tag, segments=w.segments, start=w.start, end=w.end, radius=w.radius)
            for w in m.wires
        ],
        symbols=[SymbolIn(name=s.name, formula=s.formula) for s in m.symbols],
        excitations=[
            ExcitationIn(
                tag=e.tag,
                segment=e.segment,
                voltage_re=e.voltage_re,
                voltage_im=e.voltage_im,
                kind=e.kind,
            )
            for e in m.excitations
        ],
        ground=GroundIn(
            kind=m.ground.kind,
            epsilon_r=m.ground.epsilon_r,
            conductivity=m.ground.conductivity,
            exact=m.ground.exact,
        ),
        sweep=SweepIn(start_mhz=m.sweep.start_mhz, step_mhz=m.sweep.step_mhz, count=m.sweep.count),
        extra_cards=list(m.extra_cards),
    )


def resolve_and_check(
    model: AntennaModel, max_frequency_mhz: float
) -> tuple[Resolved, list[Issue]]:
    """Symboles et formules calculés par onec, puis contrôle du modèle résolu."""
    with engine_errors():
        return validate_with_symbols(model, max_frequency_mhz)


def check_model(model: AntennaModel, max_frequency_mhz: float) -> list[str]:
    """Lève 422 si le contrôle du modèle trouve une erreur ; renvoie les avertissements.

    `max_frequency_mhz` : fréquence la plus haute du calcul demandé (λ la plus courte).
    Le modèle envoyé ensuite à onec garde ses formules : c'est onec qui les calcule.
    """
    _, issues = resolve_and_check(model, max_frequency_mhz)
    errors = [i.message for i in issues if i.severity == "error"]
    if errors:
        raise HTTPException(status_code=422, detail=" ; ".join(errors))
    return [i.message for i in issues if i.severity == "warning"]


def issue_out(i: Issue) -> IssueOut:
    return IssueOut(
        severity=i.severity,
        code=i.code,
        message=i.message,
        wires=list(i.wires),
        symbols=list(i.symbols),
    )


@contextmanager
def engine_errors() -> Iterator[None]:
    """Traduit les erreurs du moteur en codes HTTP."""
    try:
        yield
    except ModelRejected as exc:
        # onec a tourné mais refusé le modèle : c'est la requête qui est en cause
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EngineError as exc:  # onec absent, délai dépassé… : le service est en cause
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def feedpoint_out(fp: FeedpointResult) -> FeedpointOut:
    swr = fp.swr()
    return FeedpointOut(
        tag=fp.tag,
        segment=fp.segment,
        r=fp.impedance.real,
        x=fp.impedance.imag,
        swr_50=None if math.isinf(swr) else swr,
    )
