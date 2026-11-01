"""
ETL: lee los 3 CSV de origen y los carga en SQLite normalizados.

Problemas reales de los datos que este módulo resuelve:
1. CODIFICACIÓN: los archivos no siempre son UTF-8. Se ve 'CEDE�O' donde debía
   decir 'CEDEÑO'. Probamos utf-8-sig y hacemos fallback a cp1252 (Windows).
2. FECHAS INCONSISTENTES entre archivos:
     - citas_medicos / citas_pacientes: 'D-M-YYYY'  (ej. '1-10-2025')
     - citas_totales_dia: columna 'mes'='YYYY-MM' + columna 'dia'=entero
   Todo se normaliza a ISO 'YYYY-MM-DD'.
3. NOMBRES SUCIOS: el campo 'medico' viene con títulos variados y a veces como
   '"APELLIDO, NOMBRE"' (coma embebida). Usamos el módulo csv (no split) y
   colapsamos espacios/saltos. Los nombres de paciente pueden traer saltos de
   línea por exportación; también se limpian.
4. CÉDULA: se guarda tal cual como texto (cédula, pasaporte 'AT652430', etc.).

El ETL es idempotente: por defecto hace full-reload (borra y recarga), así que
correrlo dos veces no duplica datos.
"""
from __future__ import annotations

import csv
import io
import re
import sys
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator

from .config import settings
from .database import DatabaseManager, db as default_db

# Codificaciones a intentar, en orden.
_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

# Filas acumuladas en memoria antes de cada INSERT por lotes.
_BATCH_SIZE = 20_000

# Máximo de mensajes de error que recordamos (para no crecer sin control).
_MAX_REPORTED_ERRORS = 100

_WS_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------
# Utilidades de limpieza
# --------------------------------------------------------------------------
def clean_text(value: str | None) -> str:
    """Quita saltos de línea, colapsa espacios y recorta. Nunca devuelve None."""
    if value is None:
        return ""
    # Reemplaza saltos y tabs por espacio, colapsa múltiples espacios.
    return _WS_RE.sub(" ", value.replace("\r", " ").replace("\n", " ")).strip()


def normalize_medico(value: str | None) -> str:
    """Normaliza el nombre del médico: limpia espacios y uniforma a MAYÚSCULAS.

    Conserva el formato 'APELLIDO, NOMBRE' si viene así; solo normaliza espacios
    y mayúsculas para que los filtros agrupen bien.
    """
    txt = clean_text(value)
    return txt.upper()


def parse_fecha_dmy(value: str) -> str:
    """'D-M-YYYY' -> 'YYYY-MM-DD'. Lanza ValueError si no se puede parsear."""
    txt = clean_text(value)
    parts = txt.split("-")
    if len(parts) != 3:
        raise ValueError(f"Fecha no reconocida: {value!r}")
    d, m, y = (int(p) for p in parts)
    return date(y, m, d).isoformat()


def parse_fecha_mes_dia(mes: str, dia: str) -> str:
    """mes='YYYY-MM' + dia -> 'YYYY-MM-DD'."""
    mes = clean_text(mes)
    y_str, _, m_str = mes.partition("-")
    return date(int(y_str), int(m_str), int(dia)).isoformat()


def _to_int(value: str, field: str, line_no: int) -> int:
    try:
        return int(clean_text(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Valor entero inválido en '{field}' (línea {line_no}): {value!r}") from exc


# --------------------------------------------------------------------------
# Lectura robusta de CSV
# --------------------------------------------------------------------------
def _read_rows(path: Path) -> Iterator[dict[str, str]]:
    """Abre el CSV probando varias codificaciones y lo entrega como dicts.

    Decodifica el archivo COMPLETO antes de entregar la primera fila: así un
    fallo de encoding a mitad de archivo se detecta antes de insertar nada,
    y el import queda all-or-nothing por tabla.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró {path}. Coloca los 3 CSV en la carpeta de datos "
            f"(o genera una muestra con: python scripts/make_sample_data.py)."
        )
    last_err: Exception | None = None
    for enc in _ENCODINGS:
        try:
            text = path.read_text(encoding=enc)
        except UnicodeDecodeError as exc:  # pragma: no cover - depende del archivo
            last_err = exc
            continue
        yield from csv.DictReader(io.StringIO(text))
        return
    raise UnicodeError(
        f"No se pudo decodificar {path.name} con {_ENCODINGS}: {last_err}"
    )


# --------------------------------------------------------------------------
# Importadores por archivo
# --------------------------------------------------------------------------
class ETLResult:
    def __init__(self) -> None:
        self.inserted: dict[str, int] = {}
        self.skipped: dict[str, int] = {}
        self.skipped_samples: dict[str, list[str]] = {}

    def add(self, table: str, inserted: int, errors: list[str]) -> None:
        self.inserted[table] = inserted
        if errors:
            self.skipped[table] = len(errors)
            self.skipped_samples[table] = errors[:_MAX_REPORTED_ERRORS]

    def __str__(self) -> str:
        lines = ["Resultado del ETL:"]
        for table, n in self.inserted.items():
            bad = self.skipped.get(table, 0)
            extra = f"  ({bad} filas omitidas)" if bad else ""
            lines.append(f"  - {table}: {n} filas{extra}")
        return "\n".join(lines)


class ETLImporter:
    def __init__(self, database: DatabaseManager | None = None) -> None:
        self.db = database or default_db
        self._sucursales: dict[int, str] = {}
        self._persisted: set[int] = set()

    def run(self, data_dir: Path | None = None, *, full_reload: bool = True) -> ETLResult:
        data_dir = Path(data_dir) if data_dir else settings.data_dir
        self.db.init_schema()
        if full_reload:
            self.db.reset()

        result = ETLResult()
        self._sucursales = {}
        self._persisted = set()

        # Orden: primero los que aportan sucursales, al final persistimos sucursales.
        result.add(*self._import_medicos(data_dir / settings.csv_medicos))
        result.add(*self._import_pacientes(data_dir / settings.csv_pacientes))
        result.add(*self._import_totales(data_dir / settings.csv_totales))
        self._flush_sucursales()
        return result

    # ---- sucursales (dimensión compartida) --------------------------------
    def _track_sucursal(self, cod: int, nombre: str) -> None:
        if cod not in self._sucursales and nombre:
            self._sucursales[cod] = nombre

    _SUCURSALES_SQL = (
        "INSERT OR REPLACE INTO sucursales (cod_ue_mu, sucursal) VALUES (?, ?)"
    )

    def _flush_sucursales(self, cur=None) -> None:
        """Persiste las sucursales descubiertas y aún no insertadas.

        Si se pasa un cursor usa ESA conexión (evita 'database is locked':
        nunca abrimos una segunda conexión de escritura durante la carga).
        """
        pendientes = [
            (cod, nombre)
            for cod, nombre in self._sucursales.items()
            if cod not in self._persisted
        ]
        if not pendientes:
            return
        if cur is None:
            with self.db.cursor() as own_cur:
                own_cur.executemany(self._SUCURSALES_SQL, pendientes)
        else:
            cur.executemany(self._SUCURSALES_SQL, pendientes)
        self._persisted.update(cod for cod, _ in pendientes)

    @staticmethod
    def _batch_insert(
        cursor,
        sql: str,
        row_iter: Iterable[tuple[int, tuple | None]],
        before_batch=None,
    ) -> tuple[int, list[str]]:
        """Inserta por lotes de _BATCH_SIZE filas para no acumular todo en RAM.

        El iterador entrega pares (línea, tupla|None). Cuando la tupla es None
        la fila era inválida; se cuenta como omitida. Si se pasa `before_batch`
        se invoca antes de cada executemany (el ETL lo usa para persistir las
        sucursales descubiertas al parsear y no violar la FK). Devuelve
        (filas_insertadas, mensajes_de_error_acotados).
        """
        inserted = 0
        errors: list[str] = []
        batch: list[tuple] = []
        for lineno, tup in row_iter:
            if tup is None:
                if len(errors) < _MAX_REPORTED_ERRORS and lineno:
                    errors.append(lineno)
                continue
            batch.append(tup)
            if len(batch) >= _BATCH_SIZE:
                if before_batch:
                    before_batch()
                cursor.executemany(sql, batch)
                inserted += len(batch)
                batch.clear()
        if batch:
            if before_batch:
                before_batch()
            cursor.executemany(sql, batch)
            inserted += len(batch)
        return inserted, errors

    # ---- citas_medicos ----------------------------------------------------
    def _import_medicos(self, path: Path) -> tuple[str, int, list[str]]:
        errors: list[str] = []

        def rows() -> Iterator[tuple[int, tuple | None]]:
            for i, raw in enumerate(_read_rows(path), start=2):
                try:
                    cod = _to_int(raw["cod_ue_mu"], "cod_ue_mu", i)
                    suc = clean_text(raw["sucursal"])
                    self._track_sucursal(cod, suc)
                    yield i, (
                        cod,
                        parse_fecha_dmy(raw["fecha"]),
                        normalize_medico(raw["medico"]),
                        _to_int(raw["total_cupos"], "total_cupos", i),
                    )
                except (ValueError, KeyError) as exc:
                    if len(errors) < _MAX_REPORTED_ERRORS:
                        errors.append(f"L{i}: {exc}")

        self._flush_sucursales()  # garantiza las FK antes de insertar hijos
        with self.db.cursor() as cur:
            inserted, _ = self._batch_insert(
                cur,
                "INSERT INTO citas_medicos (cod_ue_mu, fecha, medico, total_cupos) "
                "VALUES (?, ?, ?, ?)",
                rows(),
                before_batch=lambda: self._flush_sucursales(cur),
            )
        return ("citas_medicos", inserted, errors)

    # ---- citas_pacientes --------------------------------------------------
    def _import_pacientes(self, path: Path) -> tuple[str, int, list[str]]:
        errors: list[str] = []

        def rows() -> Iterator[tuple[int, tuple | None]]:
            for i, raw in enumerate(_read_rows(path), start=2):
                try:
                    cod = _to_int(raw["cod_ue_mu"], "cod_ue_mu", i)
                    suc = clean_text(raw["sucursal"])
                    self._track_sucursal(cod, suc)
                    yield i, (
                        cod,
                        parse_fecha_dmy(raw["fecha"]),
                        clean_text(raw.get("hora")),
                        normalize_medico(raw.get("medico")),
                        clean_text(raw.get("especialidad")),
                        clean_text(raw.get("paciente")),
                        clean_text(raw.get("cedula")),
                    )
                except (ValueError, KeyError) as exc:
                    if len(errors) < _MAX_REPORTED_ERRORS:
                        errors.append(f"L{i}: {exc}")

        self._flush_sucursales()
        with self.db.cursor() as cur:
            inserted, _ = self._batch_insert(
                cur,
                "INSERT INTO citas_pacientes "
                "(cod_ue_mu, fecha, hora, medico, especialidad, paciente, cedula) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows(),
                before_batch=lambda: self._flush_sucursales(cur),
            )
        return ("citas_pacientes", inserted, errors)

    # ---- citas_totales_dia ------------------------------------------------
    def _import_totales(self, path: Path) -> tuple[str, int, list[str]]:
        errors: list[str] = []

        def rows() -> Iterator[tuple[int, tuple | None]]:
            for i, raw in enumerate(_read_rows(path), start=2):
                try:
                    cod = _to_int(raw["cod_ue_mu"], "cod_ue_mu", i)
                    suc = clean_text(raw["sucursal"])
                    self._track_sucursal(cod, suc)
                    yield i, (
                        cod,
                        parse_fecha_mes_dia(raw["mes"], raw["dia"]),
                        _to_int(raw["total_citas"], "total_citas", i),
                    )
                except (ValueError, KeyError) as exc:
                    if len(errors) < _MAX_REPORTED_ERRORS:
                        errors.append(f"L{i}: {exc}")

        self._flush_sucursales()
        with self.db.cursor() as cur:
            inserted, _ = self._batch_insert(
                cur,
                "INSERT INTO citas_totales_dia (cod_ue_mu, fecha, total_citas) "
                "VALUES (?, ?, ?)",
                rows(),
                before_batch=lambda: self._flush_sucursales(cur),
            )
        return ("citas_totales_dia", inserted, errors)


def run_etl(data_dir: str | Path | None = None, *, full_reload: bool = True) -> ETLResult:
    """Punto de entrada programático."""
    importer = ETLImporter()
    return importer.run(Path(data_dir) if data_dir else None, full_reload=full_reload)


if __name__ == "__main__":
    # Uso: python -m app.etl [carpeta_datos]
    target = sys.argv[1] if len(sys.argv) > 1 else None
    res = run_etl(target)
    print(res)
    for table, samples in res.skipped_samples.items():
        print(f"\nPrimeras filas omitidas en {table}:")
        for line in samples[:10]:
            print(f"  {line}")
