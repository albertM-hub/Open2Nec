"""Symboles et optimiseur dans l'API (jalon 6) : contrat JSON, flux SSE, arrêt, refus."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import optimize as route
from open2nec.engine import EngineError, find_onec
from open2nec.optimize import Criteria, Trial

client = TestClient(app)


def _onec_available() -> bool:
    try:
        find_onec()
        return True
    except EngineError:
        return False


needs_onec = pytest.mark.skipif(not _onec_available(), reason="onec absent")

DIPOLE = {
    "symbols": [{"name": "f", "formula": "14.2"}, {"name": "L", "formula": "9"}],
    "wires": [
        {"tag": 1, "segments": 21, "start": [0, "-L/2", 0], "end": [0, "L/2", 0], "radius": 0.001}
    ],
    "excitations": [{"tag": 1, "segment": 11}],
    "ground": {"kind": "free"},
}
OPTIMIZE = {
    **DIPOLE,
    "variables": [{"name": "L", "low": 8, "high": 12}],
    "objective": {"band_low_mhz": 14.2, "band_high_mhz": 14.2, "n_points": 1, "z0": 72},
}


@pytest.fixture(autouse=True)
def no_leftover_jobs():
    """Chaque test part sans recherche en cours (une seule permise à la fois)."""
    yield
    for job in list(route.JOBS.values()):
        job.stop.set()
    for job in list(route.JOBS.values()):
        with job.cond:
            job.cond.wait_for(lambda j=job: j.state != "running", 30)
    route.JOBS.clear()


def read_sse(job_id: str, last_event_id: str | None = None) -> list[tuple[str, dict]]:
    headers = {"Last-Event-ID": last_event_id} if last_event_id is not None else {}
    events, kind = [], None
    with client.stream("GET", f"/optimize/{job_id}/events", headers=headers) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                events.append((kind, json.loads(line[6:])))
    return events


# --- Contrat JSON, sans onec ------------------------------------------------------------------


def test_formula_fields_are_checked_before_onec():
    bad = json.loads(json.dumps(DIPOLE))
    bad["wires"][0]["end"][1] = "L/2\nEN"
    r = client.post("/validate", json={**bad, "max_frequency_mhz": 14.2})
    assert r.status_code == 422 and "retour à la ligne" in r.text
    bad["wires"][0]["end"][1] = "1,2"
    assert client.post("/validate", json={**bad, "max_frequency_mhz": 14.2}).status_code == 422
    bad = {**DIPOLE, "symbols": [{"name": "f x", "formula": "1"}]}
    assert client.post("/validate", json={**bad, "max_frequency_mhz": 14.2}).status_code == 422


def test_number_strings_become_numbers():
    payload = json.loads(json.dumps(DIPOLE))
    payload["symbols"] = []
    payload["wires"][0]["start"] = [0, "-5", 0]
    payload["wires"][0]["end"] = [0, " 5.0 ", 0]
    data = client.post("/validate", json={**payload, "max_frequency_mhz": 14.2}).json()
    assert data["issues"] == [] and data["wires"][0]["end"] == [0, 5, 0]


def test_symbol_rules_reported_with_rows():
    payload = {**DIPOLE, "symbols": [{"name": "L", "formula": "M"}, {"name": "M", "formula": "9"}]}
    issues = client.post("/validate", json={**payload, "max_frequency_mhz": 14.2}).json()["issues"]
    assert [(i["code"], i["symbols"]) for i in issues] == [("symbol-order", [0, 1])]


def test_optimize_setup_refused():
    bad = {**OPTIMIZE, "variables": [{"name": "zz", "low": 1, "high": 2}]}
    r = client.post("/optimize", json=bad)
    assert r.status_code == 422 and "n'existe pas" in r.text
    bad = {**OPTIMIZE, "objective": {**OPTIMIZE["objective"], "w_gain": 50}}
    assert "direction" in client.post("/optimize", json=bad).text
    assert client.get("/optimize/inconnu").status_code == 404


@pytest.fixture
def slow_evaluate(monkeypatch):
    """Essai factice de 20 ms : score = (L − 10)², sans onec."""

    def evaluate(model, values, objective, n):
        time.sleep(0.02)
        L = values["L"]
        return Trial(n, values, (L - 10) ** 2, criteria=Criteria(1.0 + abs(L - 10), 0.0))

    monkeypatch.setattr("open2nec.optimize.evaluate", evaluate)
    monkeypatch.setattr(route, "check_model", lambda *a, **k: [])


def test_one_search_at_a_time_and_stop(slow_evaluate):
    job = client.post("/optimize", json={**OPTIMIZE, "max_evaluations": 2000}).json()["id"]
    r = client.post("/optimize", json=OPTIMIZE)
    assert r.status_code == 409 and "déjà en cours" in r.text
    time.sleep(0.15)
    status = client.post(f"/optimize/{job}/stop").json()
    assert status["id"] == job
    events = read_sse(job)  # se termine : la recherche s'arrête
    done = events[-1]
    assert done[0] == "done" and done[1]["state"] == "done", done[1]["error"]
    assert done[1]["reason"] in ("stopped", "converged")
    assert done[1]["start"]["values"] == {"L": 9.0}
    assert done[1]["best"]["score"] <= done[1]["start"]["score"]
    # une nouvelle recherche est de nouveau permise
    assert client.post("/optimize", json=OPTIMIZE).status_code == 200


def test_sse_resumes_after_last_event_id(slow_evaluate):
    job = client.post("/optimize", json={**OPTIMIZE, "max_evaluations": 12}).json()["id"]
    events = read_sse(job)
    trials = [d for k, d in events if k == "trial"]
    assert [t["trial"]["n"] for t in trials] == list(range(12))
    assert events[-1][1]["reason"] == "max_evaluations"
    again = read_sse(job, last_event_id="9")
    assert [d["trial"]["n"] for k, d in again if k == "trial"] == [10, 11]
    # le meilleur transmis ne se dégrade jamais
    best = [t["best"]["score"] for t in trials]
    assert best == sorted(best, reverse=True)


def test_failure_is_reported(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("panne simulée")

    monkeypatch.setattr(route, "optimize", boom)
    monkeypatch.setattr(route, "check_model", lambda *a, **k: [])
    job = client.post("/optimize", json=OPTIMIZE).json()["id"]
    done = read_sse(job)[-1][1]
    assert (done["state"], done["error"]) == ("failed", "panne simulée")


# --- Avec onec ------------------------------------------------------------------------------


@needs_onec
def test_validate_returns_symbol_values_and_wires():
    data = client.post("/validate", json={**DIPOLE, "max_frequency_mhz": 14.2}).json()
    assert data["symbol_values"] == {"f": 14.2, "L": 9.0}
    assert data["wires"][0]["start"] == [0, -4.5, 0]
    bad = json.loads(json.dumps(DIPOLE))
    bad["wires"][0]["end"][1] = "L*q"  # onec en ferait 0 sans rien dire
    data = client.post("/validate", json={**bad, "max_frequency_mhz": 14.2}).json()
    assert [(i["code"], i["wires"]) for i in data["issues"]] == [("formula-eval", [0])]
    assert data["wires"] == []


@needs_onec
def test_simulate_with_formulas_and_blocked_by_formula_error():
    body = {**DIPOLE, "sweep": {"start_mhz": 14.2}}
    assert client.post("/simulate", json=body).status_code == 200
    bad = json.loads(json.dumps(body))
    bad["wires"][0]["end"][1] = "L*q"
    r = client.post("/simulate", json=bad)
    assert r.status_code == 422 and "incalculable" in r.text


@needs_onec
def test_export_and_import_keep_formulas():
    deck = client.post("/export", json={**DIPOLE, "sweep": {"start_mhz": 14.2}}).text
    assert "SY f=14.2\nSY L=9\n" in deck.replace("\r", "")
    assert "GW 1 21 0 -L/2 0 0 L/2 0 0.001" in deck
    model = client.post("/import", json={"content": deck}).json()["model"]
    assert [s["name"] for s in model["symbols"]] == ["f", "L"]
    assert model["wires"][0]["end"] == [0, "L/2", 0]


@needs_onec
def test_optimize_dipole_to_resonance():
    job = client.post("/optimize", json=OPTIMIZE).json()["id"]
    done = read_sse(job)[-1][1]
    assert (done["state"], done["reason"]) == ("done", "converged")
    assert done["best"]["criteria"]["swr_max"] < 1.05
    assert 10.1 < done["best"]["values"]["L"] < 10.4  # résonance du fil de 1 mm : 10,25 m
    assert client.get(f"/optimize/{job}").json()["evaluations"] == done["evaluations"]


@needs_onec
def test_optimize_refuses_invalid_start_model():
    bad = json.loads(json.dumps(OPTIMIZE))
    bad["ground"] = {"kind": "perfect"}  # fil couché sur le sol parfait
    r = client.post("/optimize", json=bad)
    assert r.status_code == 422
