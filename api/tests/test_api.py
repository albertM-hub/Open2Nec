import pytest
from fastapi.testclient import TestClient

from app.main import app
from open2nec.engine import EngineError, find_onec

client = TestClient(app)

PAYLOAD = {
    "wires": [{"tag": 1, "segments": 21, "start": [0, -5, 0], "end": [0, 5, 0], "radius": 0.001}],
    "excitations": [{"tag": 1, "segment": 11}],
    "ground": {"kind": "free"},
    "sweep": {"start_mhz": 13.0, "step_mhz": 1.0, "count": 3},
    "pattern": {"n_theta": 7, "n_phi": 5, "d_theta": 30, "d_phi": 90},
}


def _onec_available() -> bool:
    try:
        find_onec()
        return True
    except EngineError:
        return False


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_simulate_without_pattern():
    """Le front n'envoie pas de diagramme : il doit quand même recevoir les impédances."""
    # fil à 10 m de haut : sur sol réel, un fil à z = 0 est refusé par onec
    wire = {"tag": 1, "segments": 21, "start": [0, -5, 10], "end": [0, 5, 10], "radius": 0.001}
    payload = {**PAYLOAD, "wires": [wire], "pattern": None, "ground": {"kind": "real"}}
    data = client.post("/simulate", json=payload).json()
    assert len(data["frequencies"]) == 3
    assert data["frequencies"][0]["feedpoints"][0]["r"] > 0


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_invalid_payload_rejected():
    bad = {**PAYLOAD, "sweep": {"start_mhz": -1}}
    assert client.post("/simulate", json=bad).status_code == 422


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_simulate_dipole():
    r = client.post("/simulate", json=PAYLOAD)
    assert r.status_code == 200
    data = r.json()
    assert len(data["frequencies"]) == 3
    assert data["frequencies"][0]["feedpoints"][0]["r"] > 0
    assert data["warnings"] == []


def _post(**changes):
    return client.post("/simulate", json={**PAYLOAD, **changes})


def test_excitation_on_missing_wire_422():
    r = _post(excitations=[{"tag": 2, "segment": 1}])
    assert r.status_code == 422
    assert "n'existe pas" in r.json()["detail"]


def test_excitation_segment_out_of_range_422():
    r = _post(excitations=[{"tag": 1, "segment": 22}])
    assert r.status_code == 422
    assert "hors limites" in r.json()["detail"]


def test_too_many_segments_422():
    wire = {**PAYLOAD["wires"][0], "segments": 1001}
    r = _post(wires=[wire, {**wire, "tag": 2}])  # 2002 segments au total
    assert r.status_code == 422
    assert "trop lourd" in str(r.json()["detail"])


def test_pattern_budget_422():
    # grille par défaut (37 × 73) sur 101 fréquences : bien au-delà du budget
    r = _post(sweep={"start_mhz": 13.0, "step_mhz": 0.01, "count": 101}, pattern={})
    assert r.status_code == 422
    assert "diagramme trop lourd" in str(r.json()["detail"])


def test_too_many_frequencies_422():
    r = _post(sweep={"start_mhz": 13.0, "step_mhz": 0.01, "count": 202}, pattern=None)
    assert r.status_code == 422


def test_model_rejected_by_onec_422(monkeypatch):
    """onec refuse le modèle → 422 (et non 503)."""
    from app.routes import simulate as route
    from open2nec.engine import ModelRejected

    def refuse(model, timeout):
        raise ModelRejected("onec n'a calculé aucune fréquence (GEOMETRY DATA ERROR)")

    monkeypatch.setattr(route, "simulate", refuse)
    r = _post()
    assert r.status_code == 422
    assert "GEOMETRY DATA ERROR" in r.json()["detail"]


def test_engine_missing_503(monkeypatch):
    from app.routes import simulate as route

    def missing(model, timeout):
        raise EngineError("onec introuvable")

    monkeypatch.setattr(route, "simulate", missing)
    assert _post().status_code == 503


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_wire_flat_on_ground_422():
    """Fil à z = 0 sur sol réel : arrêté par le contrôle du modèle avant onec (qui planterait)."""
    r = _post(ground={"kind": "real"}, pattern=None)
    assert r.status_code == 422
    assert "à plat sur le sol" in r.json()["detail"]


# --- /pattern et /presets (jalon 2) ------------------------------------------------------

GEOMETRY = {k: PAYLOAD[k] for k in ("wires", "excitations", "ground")}


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_pattern_dipole():
    r = client.post("/pattern", json={**GEOMETRY, "frequency_mhz": 14.2})
    assert r.status_code == 200
    data = r.json()
    assert data["frequency_mhz"] == 14.2
    assert data["feedpoints"][0]["r"] > 0
    s = data["summary"]
    assert 1.9 < s["max_gain_db"] < 2.4  # dipôle en espace libre
    assert len(s["azimuth_cut"]) == 180 and s["elevation_cut"]
    assert set(s["azimuth_cut"][0]) == {"angle", "gain_db"}


def test_pattern_invalid_excitation_422():
    bad = {**GEOMETRY, "excitations": [{"tag": 1, "segment": 99}], "frequency_mhz": 14.2}
    r = client.post("/pattern", json=bad)
    assert r.status_code == 422
    assert "hors limites" in r.json()["detail"]


def test_pattern_frequency_required_positive():
    assert client.post("/pattern", json={**GEOMETRY, "frequency_mhz": 0}).status_code == 422
    assert client.post("/pattern", json=GEOMETRY).status_code == 422


def test_pattern_engine_errors(monkeypatch):
    """Même traduction des erreurs du moteur que /simulate : 422 si refus, 503 sinon."""
    from app.routes import pattern as route
    from open2nec.engine import ModelRejected

    def fail(exc):
        def _run(model, frequency_mhz, timeout):
            raise exc

        return _run

    body = {**GEOMETRY, "frequency_mhz": 14.2}
    monkeypatch.setattr(route, "simulate_pattern", fail(ModelRejected("refusé")))
    assert client.post("/pattern", json=body).status_code == 422
    monkeypatch.setattr(route, "simulate_pattern", fail(EngineError("onec introuvable")))
    assert client.post("/pattern", json=body).status_code == 503


def test_presets_are_valid_payloads():
    """Chaque modèle servi doit pouvoir être renvoyé tel quel à /simulate (contrat JSON)."""
    from app.schemas import ModelIn

    presets = client.get("/presets").json()
    ids = [p["id"] for p in presets]
    assert ids == ["dipole", "ground_plane", "yagi3", "inverted_v", "quad2"]
    for p in presets:
        ModelIn.model_validate(p["model"])  # lève si le contrat n'est pas respecté
        assert p["design_mhz"] == 14.2
        assert p["z0"] == (120.0 if p["id"] == "quad2" else 50.0)


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_preset_round_trip():
    """Le Yagi servi par /presets, renvoyé à /pattern : lobe vers +X, AV/AR > 10 dB."""
    yagi = next(p for p in client.get("/presets").json() if p["id"] == "yagi3")
    geometry = {k: yagi["model"][k] for k in ("wires", "symbols", "excitations", "ground")}
    r = client.post("/pattern", json={**geometry, "frequency_mhz": yagi["design_mhz"]})
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s["max_phi"] == 0.0 and s["front_to_back_db"] > 10


# --- /import et /export (jalon 4) --------------------------------------------------------

DATA = __import__("pathlib").Path(__file__).parents[2] / "core" / "tests" / "data"
DECK_4NEC2 = (DATA / "import_yagi_4nec2.nec").read_text()


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_import_4nec2_file():
    r = client.post("/import", json={"filename": "yagi.nec", "content": DECK_4NEC2})
    assert r.status_code == 200
    data = r.json()
    m = data["model"]
    assert len(m["wires"]) == 10 and m["excitations"][0] == {
        "tag": 2,
        "segment": 11,
        "voltage_re": 1.0,
        "voltage_im": 0.0,
        "kind": 0,
    }
    assert m["ground"]["exact"] is True and m["sweep"]["count"] == 3
    assert [e["text"] for e in data["extra"]][1] == "LD 1 1 7 7 0 4.7e-06 5.6e-11"
    assert "trappe" in data["extra"][1]["description"]
    assert data["frequency_mhz"] == 14.3 and data["dropped"] and data["notes"]


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_imported_model_simulates_with_kept_cards():
    """Le modèle importé, renvoyé tel quel, se simule : les cartes conservées passent."""
    data = client.post("/import", json={"content": DECK_4NEC2}).json()
    geometry = {k: data["model"][k] for k in ("wires", "excitations", "ground", "extra_cards")}
    r = client.post("/pattern", json={**geometry, "frequency_mhz": data["frequency_mhz"]})
    assert r.status_code == 200
    assert len(r.json()["feedpoints"]) == 2  # source éditable + source conservée


def test_import_refused_422():
    r = client.post("/import", json={"content": "CM\nCE\nSP 0 0 1 1 1 0 0 0.1\nEN\n"})
    assert r.status_code == 422 and "surfaces" in r.json()["detail"]
    assert client.post("/import", json={"content": ""}).status_code == 422


@pytest.mark.parametrize(
    "card",
    [
        "GW 9 1 0 0 0 0 0 1 0.001",  # géométrie glissée parmi les cartes conservées
        "LD 5 0 0 0 5.8e7\nRP 0 1 1",  # saut de ligne : seconde carte cachée
        "LD 5 0 0 0 abc",
        "XQ",
    ],
)
def test_extra_cards_injection_refused(card):
    r = client.post("/simulate", json={**PAYLOAD, "extra_cards": [card]})
    assert r.status_code == 422


def test_export_writes_deck_with_kept_cards():
    body = {
        **PAYLOAD,
        "ground": {"kind": "real", "epsilon_r": 5, "conductivity": 0.001, "exact": False},
        "extra_cards": ["LD 5 0 0 0 5.8e7"],
    }
    r = client.post("/export", json=body)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    lines = r.text.splitlines()
    assert "GN 0 0 0 0 5 0.001" in lines and "LD 5 0 0 0 5.8e+07" in lines
    assert "EX 0 1 11 0 1 0" in lines and lines[-2].startswith("RP ") and lines[-1] == "EN"


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_export_then_import_round_trip():
    """Un fichier enregistré se rouvre à l'identique (fils, source, sol, cartes conservées)."""
    data = client.post("/import", json={"content": DECK_4NEC2}).json()
    exported = client.post("/export", json=data["model"]).text
    again = client.post("/import", json={"content": exported}).json()
    for key in ("excitations", "ground", "extra_cards"):
        assert again["model"][key] == data["model"][key], key
    # cotes : onec n'imprime les centres de segments qu'à 5 décimales, d'où au plus 10 µm
    # d'écart sur un fil d'un seul segment (sans effet électrique)
    w1, w2 = data["model"]["wires"], again["model"]["wires"]
    assert [(w["tag"], w["segments"], w["radius"]) for w in w1] == [
        (w["tag"], w["segments"], w["radius"]) for w in w2
    ]
    for a, b in zip(w1, w2, strict=True):
        assert a["start"] == pytest.approx(b["start"], abs=2e-5)
        assert a["end"] == pytest.approx(b["end"], abs=2e-5)


# --- Balayage analysé : z0, bandes, gain avant/arrière (jalon 3) --------------------------

SWEEP_ONLY = {**PAYLOAD, "pattern": None, "sweep": {"start_mhz": 13.0, "step_mhz": 0.5, "count": 5}}


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_sweep_summary_and_z0():
    d50 = client.post("/simulate", json=SWEEP_ONLY).json()
    d75 = client.post("/simulate", json={**SWEEP_ONLY, "z0": 75}).json()
    assert len(d50["points"]) == 5 and d50["summary"]["z0"] == 50 and d75["summary"]["z0"] == 75
    p50, p75 = d50["points"][2], d75["points"][2]
    assert (p50["r"], p50["x"]) == (p75["r"], p75["x"])  # même impédance…
    assert p50["swr"] != p75["swr"]  # … ROS différent selon z0
    assert p50["gain_db"] is None  # pas de direction demandée
    assert d50["summary"]["resonances"] and d50["summary"]["min_swr"] >= 1


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_sweep_gain_in_pattern_direction():
    """Direction du maximum fournie par /pattern → gain du balayage = gain du diagramme."""
    yagi = next(p for p in client.get("/presets").json() if p["id"] == "yagi3")
    model = yagi["model"]
    geometry = {k: model[k] for k in ("wires", "symbols", "excitations", "ground")}
    s = client.post("/pattern", json={**geometry, "frequency_mhz": 14.2}).json()["summary"]
    assert s["max_theta"] == 90 - s["takeoff_deg"]
    direction = {"theta": s["max_theta"], "phi": s["max_phi"]}
    data = client.post("/simulate", json={**model, "direction": direction}).json()
    at = next(p for p in data["points"] if p["frequency_mhz"] == 14.2)
    assert at["gain_db"] == pytest.approx(s["max_gain_db"], abs=0.1)
    assert at["front_to_back_db"] == pytest.approx(s["front_to_back_db"], abs=0.1)
    assert any(b["threshold"] == 1.5 for b in data["summary"]["bands"])


def test_pattern_and_direction_exclusive():
    body = {**PAYLOAD, "direction": {"theta": 90, "phi": 0}}  # PAYLOAD contient pattern
    assert client.post("/simulate", json=body).status_code == 422
    bad = {**SWEEP_ONLY, "direction": {"theta": 200, "phi": 0}}
    assert client.post("/simulate", json=bad).status_code == 422
    assert client.post("/simulate", json={**SWEEP_ONLY, "z0": 0}).status_code == 422


def test_sweep_engine_errors(monkeypatch):
    """Chemin du balayage analysé : mêmes codes que les autres routes (422 refus, 503 moteur)."""
    from app.routes import simulate as route
    from open2nec.engine import ModelRejected

    def fail(exc):
        def _run(model, z0, direction, timeout):
            raise exc

        return _run

    monkeypatch.setattr(route, "simulate_sweep", fail(ModelRejected("refusé")))
    assert client.post("/simulate", json=SWEEP_ONLY).status_code == 422
    monkeypatch.setattr(route, "simulate_sweep", fail(EngineError("onec introuvable")))
    assert client.post("/simulate", json=SWEEP_ONLY).status_code == 503


# --- /validate (jalon 5) -----------------------------------------------------------------


def test_validate_reports_issues_with_rows():
    stub = {"tag": 2, "segments": 5, "start": [0, 0, 0], "end": [0, 0, 2], "radius": 0.001}
    body = {**GEOMETRY, "wires": [*PAYLOAD["wires"], stub], "max_frequency_mhz": 15}
    issues = client.post("/validate", json=body).json()["issues"]
    mid = next(i for i in issues if i["code"] == "mid_segment")
    assert mid["severity"] == "warning" and mid["wires"] == [0, 1]
    assert set(mid) == {"severity", "code", "message", "wires", "symbols"}


def test_validate_clean_model_and_bad_frequency():
    data = client.post("/validate", json={**GEOMETRY, "max_frequency_mhz": 15}).json()
    assert data["issues"] == [] and data["symbol_values"] == {}
    assert data["wires"][0]["end"] == [0, 5, 0]  # sans formule : fils renvoyés tels quels
    assert client.post("/validate", json={**GEOMETRY, "max_frequency_mhz": 0}).status_code == 422


def test_errors_block_calculations_before_onec(monkeypatch):
    """Une erreur du contrôle arrête /simulate et /pattern sans même lancer onec."""
    from app.routes import pattern as pattern_route
    from app.routes import simulate as simulate_route

    def never(*a, **k):
        raise AssertionError("onec ne doit pas être lancé")

    monkeypatch.setattr(simulate_route, "simulate_sweep", never)
    monkeypatch.setattr(pattern_route, "simulate_pattern", never)
    twin = {**GEOMETRY, "wires": PAYLOAD["wires"] * 2}  # deux fils superposés (même tag ici)
    r = client.post("/simulate", json={**twin, "sweep": SWEEP_ONLY["sweep"]})
    assert r.status_code == 422 and "superposés" in r.json()["detail"]
    r = client.post("/pattern", json={**twin, "frequency_mhz": 14.2})
    assert r.status_code == 422 and "superposés" in r.json()["detail"]


@pytest.mark.skipif(not _onec_available(), reason="onec absent")
def test_warnings_returned_with_results():
    coarse = {**PAYLOAD["wires"][0], "segments": 3}  # segments de 3,3 m > λ/10 à 15 MHz
    body = {**SWEEP_ONLY, "wires": [coarse], "excitations": [{"tag": 1, "segment": 2}]}
    data = client.post("/simulate", json=body).json()
    assert data["points"] and any("λ/10" in w for w in data["warnings"])
