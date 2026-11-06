"""Fichiers .nec : POST /import (fichier → modèle éditable), POST /export (modèle → fichier)."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from open2nec.importer import import_deck
from open2nec.model import FrequencySweep, RadiationGrid

from ..schemas import (
    MAX_FREQUENCIES,
    MAX_SEGMENTS_TOTAL,
    MAX_WIRES,
    ExtraCardOut,
    ImportIn,
    ImportOut,
    ModelIn,
)
from .common import engine_errors, model_to_core, model_to_in

router = APIRouter()


@router.post("/import", response_model=ImportOut)
def import_file(payload: ImportIn) -> ImportOut:
    with engine_errors():  # fichier refusé ou illisible par onec → 422 avec la raison
        res = import_deck(payload.content, payload.filename)
    model = res.model
    notes = list(res.notes)

    # Limites de calcul de l'API : refus explicite plutôt qu'une erreur de validation obscure
    total = sum(w.segments for w in model.wires)
    if total > MAX_SEGMENTS_TOTAL:
        raise HTTPException(
            422, f"modèle trop lourd : {total} segments (maximum {MAX_SEGMENTS_TOTAL})"
        )
    if len(model.wires) > MAX_WIRES:
        raise HTTPException(422, f"trop de fils : {len(model.wires)} (maximum {MAX_WIRES})")
    sweep = model.sweep
    if sweep.count > MAX_FREQUENCIES:
        # même plage de fréquences, moins de points
        span = sweep.step_mhz * (sweep.count - 1)
        model.sweep = FrequencySweep(sweep.start_mhz, span / (MAX_FREQUENCIES - 1), MAX_FREQUENCIES)
        notes.append(f"balayage ramené de {sweep.count} à {MAX_FREQUENCIES} points")

    return ImportOut(
        model=model_to_in(model),
        frequency_mhz=res.frequency_mhz,
        extra=[ExtraCardOut(text=e.text, description=e.description) for e in res.extra],
        dropped=res.dropped,
        notes=notes,
    )


@router.post("/export", response_class=PlainTextResponse)
def export_file(payload: ModelIn) -> str:
    """Texte .nec du modèle (cartes conservées comprises), lisible par 4NEC2 et onec."""
    model = model_to_core(payload)
    model.comment = "Open2Nec"
    # Grille 3D standard (pas de 5°) : le fichier se calcule tel quel dans 4NEC2 ou onec et
    # affiche un diagramme dès l'ouverture
    model.pattern = RadiationGrid()
    return model.to_deck()
