"""
Rutas FastAPI (documento 06).

Tres familias de endpoints:
- /api/...        -> JSON (para integraciones o para el front dinámico)
- /{vista}/export -> CSV con los mismos filtros de la vista (streaming, con tope)
- /               -> páginas HTML renderizadas con Jinja2 (autoescape -> anti-XSS)

Validación de entrada con los tipos de Query de FastAPI: 'page' y 'page_size'
están acotados con ge/le; las fechas se validan con un patrón ISO. Si algo no
valida, FastAPI responde 422 sin tocar la base de datos.
"""
from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path
from typing import Iterator
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from .config import settings
from .schemas import PagedResponse, Resumen
from .service import service

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Patrón de fecha ISO para validar filtros (YYYY-MM-DD).
_FECHA = r"^\d{4}-\d{2}-\d{2}$"

# Direcciones de orden permitidas (lista blanca; el default lo fija el repo).
_DIR = r"^(?i:asc|desc)$"


# ---- helpers expuestos a Jinja -------------------------------------------
def _build_url(base_url: str, filtros: dict | None = None, **overrides) -> str:
    """Construye una URL con los filtros activos (+ overrides).

    Un override con valor None/'' ELIMINA ese parámetro de la URL; se usa para
    quitar 'page' del link de export, por ejemplo.
    """
    params: dict = {k: v for k, v in (filtros or {}).items() if v not in ("", None)}
    # Los overrides se aplican ANTES de filtrar: un override None/'' elimina
    # el parámetro que pudiera venir en filtros (p. ej. page en el export).
    params.update(overrides)
    params = {k: v for k, v in params.items() if v not in ("", None)}
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _page_window(page: int, pages: int, span: int = 2) -> list[int | str]:
    """Lista de números de página para el pager: primera, última y ±span,
    con '…' en los huecos."""
    pages = max(pages, 1)
    page = min(max(page, 1), pages)
    wanted = {1, pages} | set(range(max(1, page - span), min(pages, page + span) + 1))
    out: list[int | str] = []
    prev = 0
    for n in sorted(wanted):
        if prev and n - prev > 1:
            out.append("…")
        out.append(n)
        prev = n
    return out


templates.env.globals["build_url"] = _build_url
templates.env.globals["page_window"] = _page_window


# ==========================================================================
# API JSON
# ==========================================================================
@router.get("/api/health")
def health() -> dict:
    counts = service.repo.db.table_counts()
    return {"status": "ok", "version": "0.2.0", "tablas": counts}


@router.get("/api/resumen", response_model=Resumen)
def api_resumen() -> dict:
    return service.resumen()


@router.get("/api/medicos", response_model=PagedResponse)
def api_medicos(
    cod_ue_mu: int | None = None,
    medico: str | None = Query(None, max_length=120),
    fecha_desde: str | None = Query(None, pattern=_FECHA),
    fecha_hasta: str | None = Query(None, pattern=_FECHA),
    sort: str | None = Query(None, max_length=20),
    direction: str | None = Query(None, pattern=_DIR),
    page: int = Query(1, ge=1),
    page_size: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
) -> dict:
    return service.medicos(
        page=page, page_size=page_size, cod_ue_mu=cod_ue_mu, medico=medico,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, sort=sort, direction=direction,
    )


@router.get("/api/pacientes", response_model=PagedResponse)
def api_pacientes(
    cod_ue_mu: int | None = None,
    medico: str | None = Query(None, max_length=120),
    especialidad: str | None = Query(None, max_length=120),
    cedula: str | None = Query(None, max_length=40),
    paciente: str | None = Query(None, max_length=120),
    fecha_desde: str | None = Query(None, pattern=_FECHA),
    fecha_hasta: str | None = Query(None, pattern=_FECHA),
    sort: str | None = Query(None, max_length=20),
    direction: str | None = Query(None, pattern=_DIR),
    page: int = Query(1, ge=1),
    page_size: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
) -> dict:
    return service.pacientes(
        page=page, page_size=page_size, cod_ue_mu=cod_ue_mu, medico=medico,
        especialidad=especialidad, cedula=cedula, paciente=paciente,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, sort=sort, direction=direction,
    )


@router.get("/api/totales", response_model=PagedResponse)
def api_totales(
    cod_ue_mu: int | None = None,
    fecha_desde: str | None = Query(None, pattern=_FECHA),
    fecha_hasta: str | None = Query(None, pattern=_FECHA),
    sort: str | None = Query(None, max_length=20),
    direction: str | None = Query(None, pattern=_DIR),
    page: int = Query(1, ge=1),
    page_size: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
) -> dict:
    return service.totales(
        page=page, page_size=page_size, cod_ue_mu=cod_ue_mu,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, sort=sort, direction=direction,
    )


# ==========================================================================
# Exports CSV (mismos filtros que la vista; streaming con tope de filas)
# ==========================================================================
def _csv_response(nombre: str, headers: list[str], rows: Iterator[dict]) -> StreamingResponse:
    """Arma la respuesta de export. utf-8-sig para que Excel muestre bien la Ñ."""

    def generate() -> Iterator[str]:
        buf = io.StringIO(newline="")
        writer = csv.DictWriter(buf, fieldnames=headers)
        writer.writeheader()
        yield buf.getvalue()
        for row in rows:
            buf.seek(0)
            buf.truncate(0)
            writer.writerow(row)
            yield buf.getvalue()

    hoy = date.today().isoformat()
    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}_{hoy}.csv"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/pacientes/export")
def export_pacientes(
    cod_ue_mu: int | None = None,
    medico: str | None = Query(None, max_length=120),
    especialidad: str | None = Query(None, max_length=120),
    cedula: str | None = Query(None, max_length=40),
    paciente: str | None = Query(None, max_length=120),
    fecha_desde: str | None = Query(None, pattern=_FECHA),
    fecha_hasta: str | None = Query(None, pattern=_FECHA),
    sort: str | None = Query(None, max_length=20),
    direction: str | None = Query(None, pattern=_DIR),
) -> StreamingResponse:
    rows = service.export_pacientes(
        cod_ue_mu=cod_ue_mu, medico=medico, especialidad=especialidad,
        cedula=cedula, paciente=paciente, fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta, sort=sort, direction=direction,
    )
    return _csv_response(
        "pacientes",
        ["sucursal", "fecha", "hora", "medico", "especialidad", "paciente", "cedula"],
        rows,
    )


@router.get("/medicos/export")
def export_medicos(
    cod_ue_mu: int | None = None,
    medico: str | None = Query(None, max_length=120),
    fecha_desde: str | None = Query(None, pattern=_FECHA),
    fecha_hasta: str | None = Query(None, pattern=_FECHA),
    sort: str | None = Query(None, max_length=20),
    direction: str | None = Query(None, pattern=_DIR),
) -> StreamingResponse:
    rows = service.export_medicos(
        cod_ue_mu=cod_ue_mu, medico=medico, fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta, sort=sort, direction=direction,
    )
    return _csv_response("medicos", ["sucursal", "fecha", "medico", "total_cupos"], rows)


@router.get("/totales/export")
def export_totales(
    cod_ue_mu: int | None = None,
    fecha_desde: str | None = Query(None, pattern=_FECHA),
    fecha_hasta: str | None = Query(None, pattern=_FECHA),
    sort: str | None = Query(None, max_length=20),
    direction: str | None = Query(None, pattern=_DIR),
) -> StreamingResponse:
    rows = service.export_totales(
        cod_ue_mu=cod_ue_mu, fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta, sort=sort, direction=direction,
    )
    return _csv_response("totales", ["sucursal", "fecha", "total_citas"], rows)


# ==========================================================================
# Páginas HTML
# ==========================================================================
def _common(request: Request) -> dict:
    opts = service.opciones_filtro()
    return {"request": request, "sucursales": opts["sucursales"],
            "especialidades": opts["especialidades"],
            "page_sizes": [p for p in (25, 50, 100, 200) if p <= settings.max_page_size]}


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    ctx = _common(request)
    ctx.update(service.dashboard())
    return templates.TemplateResponse(request, "index.html", ctx)


@router.get("/medicos", response_class=HTMLResponse)
def page_medicos(
    request: Request,
    cod_ue_mu: int | None = None,
    medico: str | None = Query(None, max_length=120),
    fecha_desde: str | None = Query(None, pattern=_FECHA),
    fecha_hasta: str | None = Query(None, pattern=_FECHA),
    sort: str | None = Query(None, max_length=20),
    direction: str | None = Query(None, pattern=_DIR),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=settings.max_page_size),
):
    result = service.medicos(
        page=page, page_size=page_size, cod_ue_mu=cod_ue_mu, medico=medico,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, sort=sort, direction=direction,
    )
    ctx = _common(request)
    ctx.update(result=result, filtros={
        "cod_ue_mu": cod_ue_mu, "medico": medico or "",
        "fecha_desde": fecha_desde or "", "fecha_hasta": fecha_hasta or "",
        "sort": sort or "", "direction": direction or "", "page_size": page_size or "",
    })
    return templates.TemplateResponse(request, "medicos.html", ctx)


@router.get("/pacientes", response_class=HTMLResponse)
def page_pacientes(
    request: Request,
    cod_ue_mu: int | None = None,
    medico: str | None = Query(None, max_length=120),
    especialidad: str | None = Query(None, max_length=120),
    cedula: str | None = Query(None, max_length=40),
    paciente: str | None = Query(None, max_length=120),
    fecha_desde: str | None = Query(None, pattern=_FECHA),
    fecha_hasta: str | None = Query(None, pattern=_FECHA),
    sort: str | None = Query(None, max_length=20),
    direction: str | None = Query(None, pattern=_DIR),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=settings.max_page_size),
):
    result = service.pacientes(
        page=page, page_size=page_size, cod_ue_mu=cod_ue_mu, medico=medico,
        especialidad=especialidad, cedula=cedula, paciente=paciente,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, sort=sort, direction=direction,
    )
    ctx = _common(request)
    ctx.update(result=result, filtros={
        "cod_ue_mu": cod_ue_mu, "medico": medico or "", "especialidad": especialidad or "",
        "cedula": cedula or "", "paciente": paciente or "",
        "fecha_desde": fecha_desde or "", "fecha_hasta": fecha_hasta or "",
        "sort": sort or "", "direction": direction or "", "page_size": page_size or "",
    })
    return templates.TemplateResponse(request, "pacientes.html", ctx)


@router.get("/totales", response_class=HTMLResponse)
def page_totales(
    request: Request,
    cod_ue_mu: int | None = None,
    fecha_desde: str | None = Query(None, pattern=_FECHA),
    fecha_hasta: str | None = Query(None, pattern=_FECHA),
    sort: str | None = Query(None, max_length=20),
    direction: str | None = Query(None, pattern=_DIR),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=settings.max_page_size),
):
    result = service.totales(
        page=page, page_size=page_size, cod_ue_mu=cod_ue_mu,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, sort=sort, direction=direction,
    )
    ctx = _common(request)
    ctx.update(result=result, filtros={
        "cod_ue_mu": cod_ue_mu, "fecha_desde": fecha_desde or "", "fecha_hasta": fecha_hasta or "",
        "sort": sort or "", "direction": direction or "", "page_size": page_size or "",
    })
    return templates.TemplateResponse(request, "totales.html", ctx)
