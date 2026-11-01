"""Modelos Pydantic para validar la entrada y dar forma a la salida de la API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PageMeta(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int
    has_prev: bool
    has_next: bool


class MedicoRow(BaseModel):
    id: int
    cod_ue_mu: int
    sucursal: str
    fecha: str
    medico: str
    total_cupos: int


class PacienteRow(BaseModel):
    id: int
    cod_ue_mu: int
    sucursal: str
    fecha: str
    hora: str | None = None
    medico: str | None = None
    especialidad: str | None = None
    paciente: str | None = None
    cedula: str | None = None


class TotalRow(BaseModel):
    id: int
    cod_ue_mu: int
    sucursal: str
    fecha: str
    total_citas: int


class PagedResponse(BaseModel):
    meta: PageMeta
    data: list[dict] = Field(default_factory=list)


class Resumen(BaseModel):
    filas_pacientes: int
    filas_medicos: int
    pacientes_unicos: int
    suma_total_citas: int
    fecha_min: str | None = None
    fecha_max: str | None = None
