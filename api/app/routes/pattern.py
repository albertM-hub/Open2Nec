"""POST /pattern : diagramme de rayonnement à une fréquence, résumé et deux coupes."""

from fastapi import APIRouter

from open2nec.pattern import simulate_pattern

from ..schemas import CutPointOut, PatternOut, PatternRequest, PatternSummaryOut
from .common import (
    SIMULATION_TIMEOUT_S,
    check_model,
    engine_errors,
    feedpoint_out,
    geometry_to_core,
)

router = APIRouter()


def _cut(points: list[tuple[float, float]]) -> list[CutPointOut]:
    return [CutPointOut(angle=a, gain_db=g) for a, g in points]


@router.post("/pattern", response_model=PatternOut)
def run_pattern(payload: PatternRequest) -> PatternOut:
    model = geometry_to_core(payload)
    warnings = check_model(model, payload.frequency_mhz)
    with engine_errors():
        fr, s = simulate_pattern(model, payload.frequency_mhz, timeout=SIMULATION_TIMEOUT_S)

    summary = None
    if s is not None:
        summary = PatternSummaryOut(
            max_gain_db=s.max_gain_db,
            max_phi=s.max_phi,
            max_theta=s.max_theta,
            takeoff_deg=s.takeoff_deg,
            front_to_back_db=s.front_to_back_db,
            azimuth_cut=_cut(s.azimuth_cut),
            elevation_cut=_cut(s.elevation_cut),
        )
    return PatternOut(
        frequency_mhz=fr.frequency_mhz,
        feedpoints=[feedpoint_out(fp) for fp in fr.feedpoints],
        summary=summary,
        warnings=warnings,
    )
