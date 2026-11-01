"""
Capa Service (documento 05).

NOTA DE DISEÑO: en la plantilla original se llamaba "USER_SERVICE". Como el MVP
no tiene usuarios, aquí el Service es la capa de LÓGICA DE CONSULTA: traduce
parámetros de la web (página/tamaño, orden) a limit/offset, aplica los topes
(anti-DoS), llama al Repository y arma la metadata de paginación.

Las rutas NO hablan con el Repository directamente: siempre pasan por aquí.
"""
from __future__ import annotations

from typing import Any, Iterator

from .config import settings
from .repository import Repository, repository as default_repo


class QueryService:
    def __init__(self, repo: Repository | None = None) -> None:
        self.repo = repo or default_repo

    # ---- normalización de paginación -------------------------------------
    def _bounds(self, page: int, page_size: int) -> tuple[int, int, int, int]:
        page = max(1, page)
        # Tope duro: nunca se devuelven más filas que max_page_size.
        page_size = max(1, min(page_size, settings.max_page_size))
        limit = page_size
        offset = (page - 1) * page_size
        return page, page_size, limit, offset

    @staticmethod
    def _direction(direction: str | None) -> str | None:
        """Normaliza la dirección del orden a 'asc'/'desc' (o None)."""
        if not direction:
            return None
        d = direction.lower()
        return d if d in {"asc", "desc"} else None

    @staticmethod
    def _meta(total: int, page: int, page_size: int) -> dict[str, Any]:
        pages = (total + page_size - 1) // page_size if page_size else 0
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "has_prev": page > 1,
            "has_next": page < pages,
        }

    def _package(self, rows: list[dict], total: int, page: int, page_size: int) -> dict[str, Any]:
        return {"meta": self._meta(total, page, page_size), "data": rows}

    # ---- consultas de alto nivel -----------------------------------------
    def medicos(self, *, page: int = 1, page_size: int | None = None,
                direction: str | None = None, **filtros: Any) -> dict[str, Any]:
        page, page_size, limit, offset = self._bounds(page, page_size or settings.default_page_size)
        filtros["direction"] = self._direction(direction)
        rows, total = self.repo.medicos(limit=limit, offset=offset, **filtros)
        return self._package(rows, total, page, page_size)

    def pacientes(self, *, page: int = 1, page_size: int | None = None,
                  direction: str | None = None, **filtros: Any) -> dict[str, Any]:
        page, page_size, limit, offset = self._bounds(page, page_size or settings.default_page_size)
        filtros["direction"] = self._direction(direction)
        rows, total = self.repo.pacientes(limit=limit, offset=offset, **filtros)
        return self._package(rows, total, page, page_size)

    def totales(self, *, page: int = 1, page_size: int | None = None,
                direction: str | None = None, **filtros: Any) -> dict[str, Any]:
        page, page_size, limit, offset = self._bounds(page, page_size or settings.default_page_size)
        filtros["direction"] = self._direction(direction)
        rows, total = self.repo.totales(limit=limit, offset=offset, **filtros)
        return self._package(rows, total, page, page_size)

    # ---- exports CSV (iteradores acotados) --------------------------------
    def _export(self, iter_rows: Iterator[dict], headers: list[str],
                columns: list[str]) -> Iterator[dict]:
        """Envuelve un iterador del repo y aplica el tope de exportación.
        Devuelve dicts con solo las columnas del CSV de salida."""
        count = 0
        for row in iter_rows:
            if count >= settings.max_export_rows:
                return
            count += 1
            yield {h: row.get(c, "") for h, c in zip(headers, columns)}

    def export_pacientes(self, **filtros: Any) -> Iterator[dict[str, Any]]:
        headers = ["sucursal", "fecha", "hora", "medico", "especialidad", "paciente", "cedula"]
        filtros.pop("limit", None)
        filtros.pop("offset", None)
        return self._export(self.repo.iter_pacientes(**filtros), headers, headers)

    def export_medicos(self, **filtros: Any) -> Iterator[dict[str, Any]]:
        headers = ["sucursal", "fecha", "medico", "total_cupos"]
        filtros.pop("limit", None)
        filtros.pop("offset", None)
        return self._export(self.repo.iter_medicos(**filtros), headers, headers)

    def export_totales(self, **filtros: Any) -> Iterator[dict[str, Any]]:
        headers = ["sucursal", "fecha", "total_citas"]
        filtros.pop("limit", None)
        filtros.pop("offset", None)
        return self._export(self.repo.iter_totales(**filtros), headers, headers)

    # ---- apoyo para la UI -------------------------------------------------
    def opciones_filtro(self) -> dict[str, Any]:
        return {
            "sucursales": self.repo.list_sucursales(),
            "especialidades": self.repo.list_especialidades(),
        }

    def resumen(self) -> dict[str, Any]:
        return self.repo.resumen()

    def dashboard(self) -> dict[str, Any]:
        """Datos agregados para el panel de inicio."""
        return {
            "resumen": self.repo.resumen(),
            "top_especialidades": self.repo.top_especialidades(),
            "citas_por_sucursal": self.repo.citas_por_sucursal(),
            "totales_por_mes": self.repo.totales_por_mes(),
        }


service = QueryService()
