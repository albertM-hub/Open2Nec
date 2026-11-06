"""POST /simulate : balayage en fréquence (impédance, ROS pour z0, bandes, gain avant/arrière)."""

import math
from dataclasses import replace

from fastapi import APIRouter

from open2nec import FrequencySweep, RadiationGrid, simulate
from open2nec.sweep import SweepPoint, analyze_sweep, simulate_sweep

from ..schemas import (
    BandOut,
    FrequencyOut,
    ModelIn,
    PatternPointOut,
    SimulationOut,
    SweepPointOut,
    SweepSummaryOut,
)
from .common import (
    SIMULATION_TIMEOUT_S,
    check_model,
    engine_errors,
    feedpoint_out,
    geometry_to_core,
)

router = APIRouter()


def _finite(v: float | None) -> float | None:
    return None if v is None or math.isinf(v) else v


def _point_out(p: SweepPoint) -> SweepPointOut:
    return SweepPointOut(
        frequency_mhz=p.frequency_mhz,
        r=p.impedance.real,
        x=p.impedance.imag,
        swr=_finite(p.swr),
        gamma_re=p.gamma.real,
        gamma_im=p.gamma.imag,
        gain_db=p.gain_db,
        gain_back_db=p.gain_back_db,
        front_to_back_db=p.front_to_back_db,
    )


@router.post("/simulate", response_model=SimulationOut)
def run_simulation(payload: ModelIn) -> SimulationOut:
    model = replace(
        geometry_to_core(payload),
        sweep=FrequencySweep(payload.sweep.start_mhz, payload.sweep.step_mhz, payload.sweep.count),
        pattern=RadiationGrid(**payload.pattern.model_dump()) if payload.pattern else None,
    )
    warnings = check_model(model, max(model.sweep.frequencies))
    with engine_errors():
        if payload.pattern:
            res = simulate(model, timeout=SIMULATION_TIMEOUT_S)
            points, summary = analyze_sweep(res, payload.z0)
        else:
            direction = (
                (payload.direction.theta, payload.direction.phi) if payload.direction else None
            )
            res, points, summary = simulate_sweep(
                model, payload.z0, direction, timeout=SIMULATION_TIMEOUT_S
            )

    return SimulationOut(
        frequencies=[
            FrequencyOut(
                frequency_mhz=fr.frequency_mhz,
                feedpoints=[feedpoint_out(fp) for fp in fr.feedpoints],
                max_gain_db=fr.max_gain_db if payload.pattern else None,
                pattern=[
                    PatternPointOut(theta=p.theta, phi=p.phi, gain_db=p.gain_total_db)
                    for p in fr.pattern
                ]
                if payload.pattern
                else [],
            )
            for fr in res.frequencies
        ],
        points=[_point_out(p) for p in points],
        summary=SweepSummaryOut(
            z0=summary.z0,
            min_swr=_finite(summary.min_swr),
            min_swr_mhz=summary.min_swr_mhz,
            resonances=summary.resonances,
            bands=[
                BandOut(
                    threshold=b.threshold,
                    low_mhz=b.low_mhz,
                    high_mhz=b.high_mhz,
                    low_open=b.low_open,
                    high_open=b.high_open,
                    width_khz=b.width_khz,
                )
                for b in summary.bands
            ],
        ),
        warnings=warnings,
    )
