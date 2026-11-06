"""GET /presets : modèles pré-remplis (définis et testés dans le core)."""

from fastapi import APIRouter

from open2nec.presets import PRESETS

from ..schemas import PresetOut
from .common import model_to_in

router = APIRouter()


@router.get("/presets", response_model=list[PresetOut])
def list_presets() -> list[PresetOut]:
    return [
        PresetOut(
            id=p.id,
            name=p.name,
            description=p.description,
            design_mhz=p.design_mhz,
            z0=p.z0,
            model=model_to_in(p.build()),
        )
        for p in PRESETS
    ]
