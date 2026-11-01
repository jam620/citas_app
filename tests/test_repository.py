"""Pruebas de la capa Repository: filtros, paginación, anti-inyección."""
from __future__ import annotations

from app.repository import Repository


def test_pacientes_filtro_cedula(repo: Repository):
    rows, total = repo.pacientes(cedula="8-902-547")
    assert total == 1
    assert rows[0]["paciente"] == "JOSETH CEDEÑO"


def test_pacientes_filtro_especialidad(repo: Repository):
    rows, total = repo.pacientes(especialidad="Psiquiatría")
    assert total == 1
    assert rows[0]["medico"] == "DR. JUAN PEREZ"


def test_pacientes_filtro_fecha_rango(repo: Repository):
    rows, total = repo.pacientes(fecha_desde="2025-10-02", fecha_hasta="2025-10-02")
    assert total == 1
    assert rows[0]["sucursal"] == "Centro Norte"


def test_medicos_filtro_sucursal(repo: Repository):
    rows, total = repo.medicos(cod_ue_mu=2)
    assert total == 1
    assert rows[0]["medico"] == "DRA. ANA LOPEZ"


def test_paginacion(repo: Repository):
    rows, total = repo.pacientes(limit=1, offset=0)
    assert total == 3
    assert len(rows) == 1


def test_sql_injection_no_rompe(repo: Repository):
    """Un intento de inyección se trata como texto literal, no como SQL."""
    rows, total = repo.pacientes(paciente="'; DROP TABLE citas_pacientes; --")
    assert total == 0
    # La tabla sigue existiendo y con sus datos.
    rows2, total2 = repo.pacientes()
    assert total2 == 3


def test_orden_whitelist(repo: Repository):
    # Un 'sort' no permitido cae al orden por defecto sin error.
    rows, total = repo.pacientes(sort="cedula; DROP TABLE x")
    assert total == 3
