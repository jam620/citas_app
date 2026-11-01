"""
Capa Repository (documento 04).

NOTA DE DISEÑO: en la plantilla original este archivo se llamaba
"USERS_REPOSITORY", pero este MVP no tiene autenticación ni usuarios. Aquí el
Repository es la capa de ACCESO A DATOS de las citas: encapsula todo el SQL y es
el único lugar donde se tocan tablas.

Reglas de seguridad que se cumplen SIEMPRE:
- 100% de las consultas usan parámetros enlazados (?) -> inmune a SQL injection.
- Los nombres de columna para ordenar provienen de una lista blanca, nunca del
  texto del usuario.
- La paginación tiene tope (lo aplica la capa Service) para evitar abuso.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .database import DatabaseManager, db as default_db

# Lista blanca de columnas por las que se permite ordenar, por tabla.
_SORTABLE = {
    "citas_medicos": {"fecha", "medico", "total_cupos", "sucursal"},
    "citas_pacientes": {"fecha", "hora", "medico", "especialidad", "paciente"},
    "citas_totales_dia": {"fecha", "total_citas", "sucursal"},
}


class Repository:
    def __init__(self, database: DatabaseManager | None = None) -> None:
        self.db = database or default_db

    # ---- helpers ----------------------------------------------------------
    @staticmethod
    def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(r) for r in rows]

    def _safe_order(self, table: str, sort: str | None, default: str,
                    direction: str | None = None) -> str:
        """Devuelve una cláusula ORDER BY segura (lista blanca de columna y
        dirección). Cualquier valor fuera de la lista cae al default."""
        col = sort if sort in _SORTABLE.get(table, set()) else default
        prefix = "s." if col == "sucursal" else "t."
        direction = "DESC" if (direction or "").upper() == "DESC" else "ASC"
        return f"{prefix}{col} {direction}"

    def _paged_query(
        self,
        base_sql: str,
        count_sql: str,
        params: list[Any],
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        with self.db.cursor(readonly=True) as cur:
            cur.execute(count_sql, params)
            total = cur.fetchone()["n"]
            cur.execute(base_sql, [*params, limit, offset])
            rows = self._rows_to_dicts(cur.fetchall())
        return rows, total

    @staticmethod
    def _paged_sql(select_cols: str, table: str, where: str, order: str) -> tuple[str, str]:
        join = f"JOIN sucursales s ON s.cod_ue_mu = t.cod_ue_mu"
        base = (
            f"SELECT {select_cols} FROM {table} t {join} "
            f"{where} ORDER BY {order} LIMIT ? OFFSET ?"
        )
        count = f"SELECT COUNT(*) AS n FROM {table} t {join} {where}"
        return base, count

    # ---- sucursales (para selfiles de filtro) -----------------------------
    def list_sucursales(self) -> list[dict[str, Any]]:
        with self.db.cursor(readonly=True) as cur:
            cur.execute("SELECT cod_ue_mu, sucursal FROM sucursales ORDER BY sucursal;")
            return self._rows_to_dicts(cur.fetchall())

    def list_especialidades(self) -> list[str]:
        with self.db.cursor(readonly=True) as cur:
            cur.execute(
                "SELECT DISTINCT especialidad FROM citas_pacientes "
                "WHERE especialidad <> '' ORDER BY especialidad;"
            )
            return [r["especialidad"] for r in cur.fetchall()]

    # ---- citas_medicos ----------------------------------------------------
    def medicos(
        self,
        *,
        cod_ue_mu: int | None = None,
        medico: str | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = self._build_where(
            cod_ue_mu=cod_ue_mu,
            medico=medico,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        order = self._safe_order("citas_medicos", sort, "fecha", direction)
        base, count = self._paged_sql(
            "t.id, t.cod_ue_mu, s.sucursal, t.fecha, t.medico, t.total_cupos",
            "citas_medicos", where, f"{order}, t.medico",
        )
        return self._paged_query(base, count, params, limit, offset)

    # ---- citas_pacientes --------------------------------------------------
    def pacientes(
        self,
        *,
        cod_ue_mu: int | None = None,
        medico: str | None = None,
        especialidad: str | None = None,
        cedula: str | None = None,
        paciente: str | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = self._build_where(
            cod_ue_mu=cod_ue_mu,
            medico=medico,
            especialidad=especialidad,
            cedula=cedula,
            paciente=paciente,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        order = self._safe_order("citas_pacientes", sort, "fecha", direction)
        base, count = self._paged_sql(
            "t.id, t.cod_ue_mu, s.sucursal, t.fecha, t.hora, t.medico, "
            "t.especialidad, t.paciente, t.cedula",
            "citas_pacientes", where, f"{order}, t.hora",
        )
        return self._paged_query(base, count, params, limit, offset)

    # ---- citas_totales_dia ------------------------------------------------
    def totales(
        self,
        *,
        cod_ue_mu: int | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = self._build_where(
            cod_ue_mu=cod_ue_mu,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        order = self._safe_order("citas_totales_dia", sort, "fecha", direction)
        base, count = self._paged_sql(
            "t.id, t.cod_ue_mu, s.sucursal, t.fecha, t.total_citas",
            "citas_totales_dia", where, order,
        )
        return self._paged_query(base, count, params, limit, offset)

    # ---- métricas para el dashboard --------------------------------------
    def resumen(self) -> dict[str, Any]:
        with self.db.cursor(readonly=True) as cur:
            cur.execute("SELECT COUNT(*) AS n FROM citas_pacientes;")
            pacientes = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM citas_medicos;")
            medicos = cur.fetchone()["n"]
            cur.execute(
                "SELECT COUNT(DISTINCT cedula) AS n FROM citas_pacientes "
                "WHERE cedula <> '';"
            )
            pacientes_unicos = cur.fetchone()["n"]
            cur.execute("SELECT COALESCE(SUM(total_citas),0) AS n FROM citas_totales_dia;")
            total_citas = cur.fetchone()["n"]
            cur.execute("SELECT MIN(fecha) AS a, MAX(fecha) AS b FROM citas_pacientes;")
            rango = cur.fetchone()
        return {
            "filas_pacientes": pacientes,
            "filas_medicos": medicos,
            "pacientes_unicos": pacientes_unicos,
            "suma_total_citas": total_citas,
            "fecha_min": rango["a"],
            "fecha_max": rango["b"],
        }

    def top_especialidades(self, limit: int = 8) -> list[dict[str, Any]]:
        with self.db.cursor(readonly=True) as cur:
            cur.execute(
                "SELECT COALESCE(NULLIF(especialidad,''),'(sin especialidad)') AS especialidad, "
                "COUNT(*) AS total "
                "FROM citas_pacientes GROUP BY especialidad ORDER BY total DESC LIMIT ?;",
                (limit,),
            )
            return self._rows_to_dicts(cur.fetchall())

    def citas_por_sucursal(self, limit: int = 8) -> list[dict[str, Any]]:
        with self.db.cursor(readonly=True) as cur:
            cur.execute(
                "SELECT s.sucursal, COUNT(*) AS total "
                "FROM citas_pacientes t JOIN sucursales s ON s.cod_ue_mu = t.cod_ue_mu "
                "GROUP BY s.cod_ue_mu ORDER BY total DESC LIMIT ?;",
                (limit,),
            )
            return self._rows_to_dicts(cur.fetchall())

    def totales_por_mes(self) -> list[dict[str, Any]]:
        with self.db.cursor(readonly=True) as cur:
            cur.execute(
                "SELECT substr(fecha, 1, 7) AS mes, SUM(total_citas) AS total "
                "FROM citas_totales_dia GROUP BY mes ORDER BY mes;"
            )
            return self._rows_to_dicts(cur.fetchall())

    # ---- construcción de WHERE (parametrizado) ---------------------------
    @staticmethod
    def _build_where(**filters: Any) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        mapping_exact = {
            "cod_ue_mu": "t.cod_ue_mu = ?",
            "especialidad": "t.especialidad = ?",
        }
        mapping_like = {
            "medico": "t.medico LIKE ?",
            "paciente": "t.paciente LIKE ?",
            "cedula": "t.cedula LIKE ?",
        }

        for key, sql in mapping_exact.items():
            val = filters.get(key)
            if val not in (None, ""):
                clauses.append(sql)
                params.append(val)

        for key, sql in mapping_like.items():
            val = filters.get(key)
            if val not in (None, ""):
                clauses.append(sql)
                params.append(f"%{val}%")

        if filters.get("fecha_desde"):
            clauses.append("t.fecha >= ?")
            params.append(filters["fecha_desde"])
        if filters.get("fecha_hasta"):
            clauses.append("t.fecha <= ?")
            params.append(filters["fecha_hasta"])

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params


repository = Repository()
