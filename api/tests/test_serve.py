"""Service complet de l'image Docker (jalon 7) : interface sous /, API sous /api, en-têtes."""

import json

import pytest
from fastapi.testclient import TestClient

from app.serve import CSP, create_app


@pytest.fixture
def client(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Open2Nec</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    return TestClient(create_app(tmp_path))


def test_interface_and_api_share_one_origin(client):
    r = client.get("/")
    assert r.status_code == 200 and "<title>Open2Nec</title>" in r.text
    assert client.get("/assets/app.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/health").status_code == 404  # l'API n'est que sous /api


def test_security_headers_everywhere(client):
    for path in ("/", "/api/health", "/api/presets"):
        h = client.get(path).headers
        assert h["content-security-policy"] == CSP
        assert h["x-content-type-options"] == "nosniff"
    assert "connect-src 'self'" in CSP and "default-src 'self'" in CSP


def test_api_errors_and_docs(client):
    assert client.post("/api/simulate", json={}).status_code == 422
    assert client.get("/docs").status_code == 404  # pas de documentation exposée


def test_missing_interface_is_explained(tmp_path):
    with pytest.raises(RuntimeError, match="npm run build"):
        create_app(tmp_path / "absent")


def test_interface_found_through_environment(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>Open2Nec</title>")
    monkeypatch.setenv("OPEN2NEC_WEB_DIST", str(tmp_path))
    assert TestClient(create_app()).get("/").status_code == 200
    monkeypatch.setenv("OPEN2NEC_WEB_DIST", str(tmp_path / "absent"))
    with pytest.raises(RuntimeError, match="interface introuvable"):
        create_app()


def test_presets_through_mounted_api(client):
    presets = client.get("/api/presets").json()
    assert json.dumps(presets) and presets[0]["id"] == "dipole"
