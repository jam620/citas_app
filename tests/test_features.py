"""Pruebas de las mejoras v0.2: orden en HTML, pager, export CSV, dashboard."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.repository as repository_mod
import app.routes as routes_mod
import app.service as service_mod
from app.config import settings
from app.database import DatabaseManager
from app.etl import ETLImporter
from app.repository import Repository
from app.routes import _build_url, _page_window
from app.service import QueryService


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    db = DatabaseManager(tmp_path / "api.db")
    d = tmp_path / "data"
    d.mkdir()
    (d / "citas_medicos.csv").write_text(
        "cod_ue_mu,sucursal,fecha,medico,total_cupos\n"
        "1,Suc Uno,1-10-2025,DR. JUAN PEREZ,10\n"
        "1,Suc Uno,2-10-2025,DR. BRUNO DIAZ,7\n"
        "1,Suc Uno,3-10-2025,DR. ALICIA COSTA,5\n",
        encoding="utf-8")
    (d / "citas_pacientes.csv").write_text(
        "cod_ue_mu,sucursal,fecha,hora,medico,especialidad,paciente,cedula\n"
        "1,Suc Uno,1-10-2025,09:00:00,DR. JUAN PEREZ,Medicina General,JUAN RIOS,8-1-1\n"
        "1,Suc Uno,2-10-2025,10:00:00,DR. BRUNO DIAZ,Pediatria,ANA CRUZ,8-2-2\n"
        "1,Suc Uno,3-10-2025,11:00:00,DR. ALICIA COSTA,Psicologia,ZOE DIAZ,8-3-3\n",
        encoding="utf-8")
    (d / "citas_totales_dia.csv").write_text(
        "cod_ue_mu,sucursal,mes,dia,total_citas\n"
        "1,Suc Uno,2025-10,1,437\n"
        "1,Suc Uno,2025-10,2,100\n"
        "1,Suc Uno,2025-10,3,50\n",
        encoding="utf-8")
    ETLImporter(db).run(d)

    repo = Repository(db)
    svc = QueryService(repo)
    import app.database as database_mod
    monkeypatch.setattr(database_mod, "db", db)
    monkeypatch.setattr(repository_mod, "repository", repo)
    monkeypatch.setattr(service_mod, "service", svc)
    monkeypatch.setattr(routes_mod, "service", svc)

    from app.main import create_app
    return TestClient(create_app())


# ---- unit: helpers de plantilla ------------------------------------------
def test_page_window_bordes():
    assert _page_window(1, 1) == [1]
    assert _page_window(1, 10)[:4] == [1, 2, 3, "…"]
    assert _page_window(5, 10) == [1, "…", 3, 4, 5, 6, 7, "…", 10]
    assert _page_window(99, 10)[-1] == 10  # página fuera de rango se acota


def test_build_url_quita_page_en_export():
    filtros = {"medico": "PEREZ", "page": "3", "page_size": 50}
    url = _build_url("/pacientes/export", filtros, page=None, page_size=None)
    assert url == "/pacientes/export?medico=PEREZ"
    url2 = _build_url("/pacientes", {"medico": "A B", "sort": "fecha", "direction": "desc"})
    assert url2 == "/pacientes?medico=A+B&sort=fecha&direction=desc"


# ---- orden en páginas HTML ------------------------------------------------
def test_orden_por_medico_asc(client):
    r = client.get("/pacientes", params={"sort": "medico", "direction": "asc"})
    assert r.status_code == 200
    assert "▲" in r.text
    assert r.text.find("ALICIA COSTA") < r.text.find("JUAN PEREZ")


def test_orden_desc_por_fecha(client):
    r = client.get("/pacientes", params={"sort": "fecha", "direction": "desc"})
    assert r.status_code == 200
    assert "▼" in r.text
    assert r.text.find("ZOE DIAZ") < r.text.find("JUAN RIOS")


def test_orden_invalido_cae_al_default(client):
    # 'sort' fuera de la lista blanca del repo cae al orden por defecto (200).
    r = client.get("/pacientes", params={"sort": "cedula; DROP TABLE x"})
    assert r.status_code == 200


def test_orden_bad_request_con_valor_largo(client):
    # direction fuera de la lista blanca de la regex -> 422 antes de tocar BD
    r = client.get("/medicos", params={"direction": "not-desc"})
    assert r.status_code == 422


# ---- pager ------------------------------------------------------------------
def test_pager_muestra_numeros(client):
    r = client.get("/totales", params={"page_size": 1})
    assert r.status_code == 200
    assert 'class="current"' in r.text  # página activa resaltada


# ---- exports CSV --------------------------------------------------------------
def test_export_pacientes_con_filtro(client):
    r = client.get("/pacientes/export", params={"cedula": "8-2-2"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    body = r.text
    assert body.splitlines()[0] == "sucursal,fecha,hora,medico,especialidad,paciente,cedula"
    assert "ANA CRUZ" in body
    assert "JUAN RIOS" not in body  # el filtro se respetó


def test_export_respeta_tope_de_filas(client, monkeypatch):
    nuevo = dataclasses.replace(settings, max_export_rows=2)
    monkeypatch.setattr(service_mod, "settings", nuevo)
    r = client.get("/pacientes/export")
    lineas = [ln for ln in r.text.splitlines() if ln.strip()]
    assert len(lineas) == 3  # cabecera + 2 filas (tope)


def test_export_medicos_y_totales(client):
    r1 = client.get("/medicos/export")
    assert "DR. BRUNO DIAZ,7" in r1.text
    r2 = client.get("/totales/export")
    assert "437" in r2.text


def test_export_sin_bd_no_explota(client):
    # filtro sin resultados -> CSV solo con cabecera
    r = client.get("/pacientes/export", params={"cedula": "NOEXISTE"})
    assert r.status_code == 200
    assert len(r.text.splitlines()) == 1


# ---- dashboard ------------------------------------------------------------------
def test_dashboard_html_agregados(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Top especialidades" in r.text
    assert "bar-fill" in r.text
    assert "Citas totales por mes" in r.text


def test_api_resumen_pacientes_unicos(client):
    r = client.get("/api/resumen")
    assert r.status_code == 200
    assert r.json()["pacientes_unicos"] == 3


def test_health_incluye_conteos(client):
    r = client.get("/api/health")
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.2.0"
    assert body["tablas"]["citas_pacientes"] == 3


def test_csp_header_presente(client):
    r = client.get("/api/health")
    assert "default-src 'self'" in r.headers.get("Content-Security-Policy", "")
