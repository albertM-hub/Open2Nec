"""Optimiseur : POST /optimize (démarre), GET /optimize/{id}/events (progression en SSE),
GET /optimize/{id} (état), POST /optimize/{id}/stop (arrêt, le meilleur essai est gardé).

La recherche (core) tourne dans un thread ; une seule à la fois. Chaque essai est gardé en
mémoire : le flux SSE peut reprendre où il s'était arrêté (en-tête Last-Event-ID, que le
navigateur renvoie seul à la reconnexion). Une recherche terminée est oubliée après 10 minutes.
"""

from __future__ import annotations

import json
import math
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from open2nec.optimize import (
    Objective,
    OptimizerUnavailable,
    Trial,
    Variable,
    check_setup,
    optimize,
)

from ..schemas import CriteriaOut, OptimizeIn, OptimizeStarted, OptimizeStatus, TrialOut
from .common import check_model, geometry_to_core

router = APIRouter()

KEEP_FINISHED_S = 600.0
KEEPALIVE_S = 15.0  # commentaire SSE envoyé faute d'essai, pour garder la connexion


def trial_out(t: Trial) -> TrialOut:
    c = t.criteria
    return TrialOut(
        n=t.n,
        values=t.values,
        score=t.score,
        criteria=None
        if c is None
        else CriteriaOut(
            swr_max=None if math.isinf(c.swr_max) else c.swr_max,
            swr_loss_db=c.swr_loss_db,
            gain_db=c.gain_db,
            fb_db=c.fb_db,
        ),
        error=t.error,
    )


@dataclass
class Job:
    id: str
    max_evaluations: int
    state: str = "running"  # "running", "done", "failed"
    reason: str | None = None
    error: str | None = None
    events: list[str] = field(default_factory=list)  # JSON de chaque essai, dans l'ordre
    start: TrialOut | None = None
    best: TrialOut | None = None
    finished_at: float | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    cond: threading.Condition = field(default_factory=threading.Condition)

    def status(self) -> OptimizeStatus:
        with self.cond:
            return OptimizeStatus(
                id=self.id,
                state=self.state,  # type: ignore[arg-type]
                reason=self.reason,
                error=self.error,
                evaluations=len(self.events),
                max_evaluations=self.max_evaluations,
                start=self.start,
                best=self.best,
            )


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


def _purge() -> None:
    now = time.monotonic()
    with JOBS_LOCK:
        for jid in [
            j.id for j in JOBS.values() if j.finished_at and now - j.finished_at > KEEP_FINISHED_S
        ]:
            del JOBS[jid]


def _job(job_id: str) -> Job:
    _purge()
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "optimisation inconnue ou expirée")
    return job


def _run(job: Job, model, variables, objective, max_evaluations) -> None:
    def progress(trial: Trial, best: Trial) -> None:
        t, b = trial_out(trial), trial_out(best)
        with job.cond:
            if trial.n == 0:
                job.start = t
            job.best = b
            job.events.append(json.dumps({"trial": t.model_dump(), "best": b.model_dump()}))
            job.cond.notify_all()

    try:
        result = optimize(
            model,
            variables,
            objective,
            max_evaluations,
            on_progress=progress,
            should_stop=job.stop.is_set,
        )
        with job.cond:
            job.state, job.reason = "done", result.reason
    except Exception as exc:  # noqa: BLE001 — toute panne doit finir la recherche proprement
        with job.cond:
            job.state, job.error = "failed", str(exc) or type(exc).__name__
    finally:
        with job.cond:
            job.finished_at = time.monotonic()
            job.cond.notify_all()


@router.post("/optimize", response_model=OptimizeStarted)
def start_optimize(payload: OptimizeIn) -> OptimizeStarted:
    _purge()
    with JOBS_LOCK:
        if any(j.state == "running" for j in JOBS.values()):
            raise HTTPException(409, "une optimisation est déjà en cours")
    model = geometry_to_core(payload)
    o = payload.objective
    objective = Objective(
        band_low_mhz=o.band_low_mhz,
        band_high_mhz=o.band_high_mhz,
        n_points=o.n_points,
        z0=o.z0,
        direction=(o.direction.theta, o.direction.phi) if o.direction else None,
        w_swr=o.w_swr,
        w_gain=o.w_gain,
        w_fb=o.w_fb,
        fb_cap_db=o.fb_cap_db,
    )
    variables = [Variable(v.name, v.low, v.high) for v in payload.variables]
    try:
        check_setup(model, variables, objective)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        import scipy  # noqa: F401 — refus immédiat plutôt qu'un échec dans le thread
    except ImportError as exc:
        raise HTTPException(503, str(OptimizerUnavailable())) from exc
    # Le modèle de départ doit être valable (les essais refusés, eux, sont seulement pénalisés)
    check_model(model, objective.band_high_mhz)

    job = Job(uuid.uuid4().hex, payload.max_evaluations)
    with JOBS_LOCK:
        if any(j.state == "running" for j in JOBS.values()):  # course entre deux requêtes
            raise HTTPException(409, "une optimisation est déjà en cours")
        JOBS[job.id] = job
    threading.Thread(
        target=_run,
        args=(job, model, variables, objective, payload.max_evaluations),
        name=f"optimize-{job.id[:8]}",
        daemon=True,
    ).start()
    return OptimizeStarted(id=job.id)


@router.get("/optimize/{job_id}", response_model=OptimizeStatus)
def optimize_status(job_id: str) -> OptimizeStatus:
    return _job(job_id).status()


@router.post("/optimize/{job_id}/stop", response_model=OptimizeStatus)
def stop_optimize(job_id: str) -> OptimizeStatus:
    job = _job(job_id)
    job.stop.set()
    return job.status()


@router.get("/optimize/{job_id}/events")
def optimize_events(
    job_id: str, last_event_id: str | None = Header(default=None)
) -> StreamingResponse:
    """Flux SSE : un événement « trial » par essai (id = numéro), puis « done » avec l'état."""
    job = _job(job_id)
    try:
        sent = int(last_event_id) + 1 if last_event_id is not None else 0
    except ValueError:
        sent = 0

    def stream() -> Iterator[str]:
        nonlocal sent
        while True:
            with job.cond:
                job.cond.wait_for(
                    lambda n=sent: len(job.events) > n or job.state != "running", KEEPALIVE_S
                )
                new = job.events[sent:]
                finished = job.state != "running"
            for data in new:
                yield f"id: {sent}\nevent: trial\ndata: {data}\n\n"
                sent += 1
            if finished and not new:
                yield f"event: done\ndata: {job.status().model_dump_json()}\n\n"
                return
            if not new:
                yield ": attente\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
