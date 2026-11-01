"""Pruebas de las rutas FastAPI con TestClient, usando una BD temporal."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.database as database_mod
import app.repository as repository_mod
import app.service as service_mod
from app.database import DatabaseManager
from app.etl import ETLImporter
from app.repository import Repository
from app.service import QueryService


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    # BD temporal poblada.
    db = DatabaseManager(tmp_path / "api.db")
    d = tmp_path / "data"
    d.mkdir()
    (d / "citas_medicos.csv").write_text(
        "cod_ue_mu,sucursal,fecha,medico,total_cupos\n"
        "1,Suc Uno,1-10-2025,DR. JUAN PEREZ,10\n", encoding="utf-8")
    (d / "citas_pacientes.csv").write_text(
        "cod_ue_mu,sucursal,fecha,hora,medico,especialidad,paciente,cedula\n"
        "1,Suc Uno,1-10-2025,09:00:00,DR. JUAN PEREZ,Medicina General,JUAN RIOS,8-1-1\n",
        encoding="utf-8")
    (d / "citas_totales_dia.csv").write_text(
        "cod_ue_mu,sucursal,mes,dia,total_citas\n1,Suc Uno,2026-10,1,437\n", encoding="utf-8")
    ETLImporter(db).run(d)

    # Inyectamos esta BD en los singletons que usan las rutas.
    repo = Repository(db)
    svc = QueryService(repo)
    monkeypatch.setattr(database_mod, "db", db)
    monkeypatch.setattr(repository_mod, "repository", repo)
    monkeypatch.setattr(service_mod, "service", svc)
    # routes importó 'service' por nombre; lo repibleamos también.
    import app.routes as routes_mod
    monkeypatch.setattr(routes_mod, "service", svc)

    from app.main import create_app
    return TestClient(create_app())


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_api_pacientes_json(client):
    r = client.get("/api/pacientes")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["paciente"] == "JUAN RIOS"


def test_api_pacientes_filtro(client):
    r = client.get("/api/pacientes", params={"cedula": "8-1-1"})
    assert r.json()["meta"]["total"] == 1
    r2 = client.get("/api/pacientes", params={"cedula": "NOEXISTE"})
    assert r2.json()["meta"]["total"] == 0


def test_api_valida_fecha_mal(client):
    # Fecha con formato inválido -> 422 de validación.
    r = client.get("/api/pacientes", params={"fecha_desde": "01/10/2025"})
    assert r.status_code == 422


def test_api_tope_page_size(client):
    # page_size por encima del máximo -> 422 (lo bloquea la validación de Query).
    r = client.get("/api/pacientes", params={"page_size": 99999})
    assert r.status_code == 422


def test_home_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Panel de consulta" in r.text


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
