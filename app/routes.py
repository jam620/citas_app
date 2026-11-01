"""
Rutas FastAPI (documento 06).

Dos familias de endpoints:
- /api/...  -> JSON (para integraciones o para el front dinámico)
- /         -> páginas HTML renderizadas con Jinja2 (autoescape -> anti-XSS)

Validación de entrada con los tipos de Query de FastAPI: 'page' y 'page_size'
están acotados con ge/le; las fechas se validan con un patrón ISO. Los
formularios HTML (method GET) envían TODOS los campos, incluso vacíos, por lo
que los tipos opcionales tratan la cadena vacía como "sin filtro" (ver
_blank_as_none) en lugar de responder 422.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BeforeValidator

from . import VERSION
from .config import settings
from .schemas import PagedResponse, Resumen
from .service import service

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

import re

# Patrón de fecha ISO para validar filtros (YYYY-MM-DD).
_FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Direcciones de orden permitidas (lista blanca; el default lo fija el repo).
_DIR_RE = re.compile(r"^(?i:asc|desc)$")


# ---- tipos de query tolerantes a cadenas vacías ---------------------------
def _blank_as_none(value: Any) -> Any:
    """Los formularios GET envían todos los campos: '' significa 'sin filtro'."""
    return None if value == "" else value


def _int_validator(value: Any) -> Any:
    value = _blank_as_none(value)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("Debe ser un número entero.") from None


def _fecha_validator(value: Any) -> Any:
    value = _blank_as_none(value)
    if value is None:
        return None
    if not _FECHA_RE.match(value):
        raise ValueError("La fecha debe tener formato YYYY-MM-DD.")
    return value


def _direction_validator(value: Any) -> Any:
    value = _blank_as_none(value)
    if value is None:
        return None
    if not _DIR_RE.match(value):
        raise ValueError("La dirección debe ser 'asc' o 'desc'.")
    return value.lower()


def _page_size_validator(value: Any) -> Any:
    value = _int_validator(value)
    if value is None:
        return None
    if not (1 <= value <= settings.max_page_size):
        raise ValueError(f"page_size debe estar entre 1 y {settings.max_page_size}.")
    return value


# Nota: la validación va DENTRO del BeforeValidator a propósito. Combinar
# restricciones de Query (pattern/ge/le) con BeforeValidator hace que pydantic
# las descarte silenciosamente; con validators explícitos eso no puede pasar.
OptionalInt = Annotated[int | None, BeforeValidator(_int_validator)]
OptionalFecha = Annotated[str | None, BeforeValidator(_fecha_validator)]
OptionalDireccion = Annotated[str | None, BeforeValidator(_direction_validator)]
PageSizeParam = Annotated[int | None, BeforeValidator(_page_size_validator)]


# ---- helpers expuestos a Jinja -------------------------------------------
def _build_url(base_url: str, filtros: dict | None = None, **overrides) -> str:
    """Construye una URL con los filtros activos (+ overrides).

    Un override con valor None/'' ELIMINA ese parámetro de la URL; se usa para
    quitar 'page' de los links de orden, por ejemplo.
    """
    params: dict = {k: v for k, v in (filtros or {}).items() if v not in ("", None)}
    # Los overrides se aplican ANTES de filtrar: un override None/'' elimina
    # el parámetro que pudiera venir en filtros (p. ej. page en los links).
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
    return {"status": "ok", "version": VERSION, "tablas": counts}


@router.get("/api/resumen", response_model=Resumen)
def api_resumen() -> dict:
    return service.resumen()


@router.get("/api/medicos", response_model=PagedResponse)
def api_medicos(
    cod_ue_mu: OptionalInt = None,
    medico: str | None = Query(None, max_length=120),
    fecha_desde: OptionalFecha = None,
    fecha_hasta: OptionalFecha = None,
    sort: str | None = Query(None, max_length=20),
    direction: OptionalDireccion = None,
    page: int = Query(1, ge=1),
    page_size: PageSizeParam = settings.default_page_size,
) -> dict:
    return service.medicos(
        page=page, page_size=page_size, cod_ue_mu=cod_ue_mu, medico=medico,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, sort=sort, direction=direction,
    )


@router.get("/api/pacientes", response_model=PagedResponse)
def api_pacientes(
    cod_ue_mu: OptionalInt = None,
    medico: str | None = Query(None, max_length=120),
    especialidad: str | None = Query(None, max_length=120),
    cedula: str | None = Query(None, max_length=40),
    paciente: str | None = Query(None, max_length=120),
    fecha_desde: OptionalFecha = None,
    fecha_hasta: OptionalFecha = None,
    sort: str | None = Query(None, max_length=20),
    direction: OptionalDireccion = None,
    page: int = Query(1, ge=1),
    page_size: PageSizeParam = settings.default_page_size,
) -> dict:
    return service.pacientes(
        page=page, page_size=page_size, cod_ue_mu=cod_ue_mu, medico=medico,
        especialidad=especialidad, cedula=cedula, paciente=paciente,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, sort=sort, direction=direction,
    )


@router.get("/api/totales", response_model=PagedResponse)
def api_totales(
    cod_ue_mu: OptionalInt = None,
    fecha_desde: OptionalFecha = None,
    fecha_hasta: OptionalFecha = None,
    sort: str | None = Query(None, max_length=20),
    direction: OptionalDireccion = None,
    page: int = Query(1, ge=1),
    page_size: PageSizeParam = settings.default_page_size,
) -> dict:
    return service.totales(
        page=page, page_size=page_size, cod_ue_mu=cod_ue_mu,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, sort=sort, direction=direction,
    )


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
    cod_ue_mu: OptionalInt = None,
    medico: str | None = Query(None, max_length=120),
    fecha_desde: OptionalFecha = None,
    fecha_hasta: OptionalFecha = None,
    sort: str | None = Query(None, max_length=20),
    direction: OptionalDireccion = None,
    page: int = Query(1, ge=1),
    page_size: PageSizeParam = None,
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
    cod_ue_mu: OptionalInt = None,
    medico: str | None = Query(None, max_length=120),
    especialidad: str | None = Query(None, max_length=120),
    cedula: str | None = Query(None, max_length=40),
    paciente: str | None = Query(None, max_length=120),
    fecha_desde: OptionalFecha = None,
    fecha_hasta: OptionalFecha = None,
    sort: str | None = Query(None, max_length=20),
    direction: OptionalDireccion = None,
    page: int = Query(1, ge=1),
    page_size: PageSizeParam = None,
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
    cod_ue_mu: OptionalInt = None,
    fecha_desde: OptionalFecha = None,
    fecha_hasta: OptionalFecha = None,
    sort: str | None = Query(None, max_length=20),
    direction: OptionalDireccion = None,
    page: int = Query(1, ge=1),
    page_size: PageSizeParam = None,
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
