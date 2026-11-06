"""POST /validate : contrôle du modèle (erreurs, avertissements, conseils), sans calcul.

Avec des symboles ou des formules, onec les calcule (lecture sans calcul, quelques ms) : la
réponse donne aussi leurs valeurs et les fils en nombres, pour l'affichage et la vue 3D.
"""

from fastapi import APIRouter

from ..schemas import ResolvedWireOut, ValidateIn, ValidateOut
from .common import geometry_to_core, issue_out, resolve_and_check

router = APIRouter()


@router.post("/validate", response_model=ValidateOut)
def validate(payload: ValidateIn) -> ValidateOut:
    res, issues = resolve_and_check(geometry_to_core(payload), payload.max_frequency_mhz)
    wires = res.model.wires if res.model else []
    return ValidateOut(
        issues=[issue_out(i) for i in issues],
        symbol_values=res.values,
        wires=[ResolvedWireOut(start=w.start, end=w.end, radius=w.radius) for w in wires],
    )
