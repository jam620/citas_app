"""Fixtures compartidas: una BD temporal poblada con datos mínimos."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.database import DatabaseManager
from app.etl import ETLImporter
from app.repository import Repository
from app.service import QueryService


MEDICOS = [
    ["cod_ue_mu", "sucursal", "fecha", "medico", "total_cupos"],
    ["1", "Policlínica Test", "1-10-2025", "DR. JUAN PEREZ", "10"],
    ["1", "Policlínica Test", "1-10-2025", '"DRA. SAMUDIO, PATRICIA"', "5"],
    ["2", "Centro Norte", "2-10-2025", "DRA. ANA LOPEZ", "8"],
]

PACIENTES = [
    ["cod_ue_mu", "sucursal", "fecha", "hora", "medico", "especialidad", "paciente", "cedula"],
    ["1", "Policlínica Test", "1-10-2025", "09:00:00", "DR. JUAN PEREZ", "Medicina General", "JOSETH CEDEÑO", "8-902-547"],
    ["1", "Policlínica Test", "1-10-2025", "10:00:00", "DR. JUAN PEREZ", "Psiquiatría", "ALCIDES CORDOBA", "AT652430"],
    ["2", "Centro Norte", "2-10-2025", "11:00:00", "DRA. ANA LOPEZ", "Pediatría", "MARIA RIOS", "2-74-382"],
]

TOTALES = [
    ["cod_ue_mu", "sucursal", "mes", "dia", "total_citas"],
    ["1", "Policlínica Test", "2026-10", "1", "437"],
    ["2", "Centro Norte", "2026-10", "2", "100"],
]


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    # Escribimos manualmente para preservar las comillas embebidas del caso SAMUDIO.
    lines = []
    for row in rows:
        lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    _write_csv(d / "citas_medicos.csv", MEDICOS)
    _write_csv(d / "citas_pacientes.csv", PACIENTES)
    _write_csv(d / "citas_totales_dia.csv", TOTALES)
    return d


@pytest.fixture
def database(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(tmp_path / "test.db")


@pytest.fixture
def loaded(database: DatabaseManager, data_dir: Path) -> DatabaseManager:
    ETLImporter(database).run(data_dir)
    return database


@pytest.fixture
def repo(loaded: DatabaseManager) -> Repository:
    return Repository(loaded)


@pytest.fixture
def svc(repo: Repository) -> QueryService:
    return QueryService(repo)
