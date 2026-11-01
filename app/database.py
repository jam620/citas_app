"""
DatabaseManager: gestiona la conexión SQLite y el esquema.

Decisiones de diseño:
- SQLite por archivo único (cero configuración para el MVP).
- `row_factory = sqlite3.Row` para obtener filas tipo dict.
- Claves foráneas activadas (PRAGMA foreign_keys = ON).
- Toda consulta de la app usa parámetros enlazados (anti SQL injection); esta
  clase nunca construye SQL concatenando valores del usuario.
- Para servir peticiones web usamos conexiones en modo solo lectura cuando el
  archivo ya existe, de modo que un bug en una ruta no pueda alterar los datos.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS sucursales (
    cod_ue_mu INTEGER PRIMARY KEY,
    sucursal  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citas_medicos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cod_ue_mu    INTEGER NOT NULL,
    fecha        TEXT    NOT NULL,   -- ISO 'YYYY-MM-DD'
    medico       TEXT    NOT NULL,
    total_cupos  INTEGER NOT NULL,
    FOREIGN KEY (cod_ue_mu) REFERENCES sucursales(cod_ue_mu)
);

CREATE TABLE IF NOT EXISTS citas_pacientes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cod_ue_mu    INTEGER NOT NULL,
    fecha        TEXT    NOT NULL,   -- ISO 'YYYY-MM-DD'
    hora         TEXT,
    medico       TEXT,
    especialidad TEXT,
    paciente     TEXT,
    cedula       TEXT,               -- SIEMPRE texto: hay cédulas, pasaportes, etc.
    FOREIGN KEY (cod_ue_mu) REFERENCES sucursales(cod_ue_mu)
);

CREATE TABLE IF NOT EXISTS citas_totales_dia (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cod_ue_mu   INTEGER NOT NULL,
    fecha       TEXT    NOT NULL,    -- ISO 'YYYY-MM-DD'
    total_citas INTEGER NOT NULL,
    FOREIGN KEY (cod_ue_mu) REFERENCES sucursales(cod_ue_mu)
);

-- Índices para acelerar los filtros más comunes.
CREATE INDEX IF NOT EXISTS ix_medicos_fecha        ON citas_medicos(fecha);
CREATE INDEX IF NOT EXISTS ix_medicos_medico       ON citas_medicos(medico);
CREATE INDEX IF NOT EXISTS ix_medicos_suc          ON citas_medicos(cod_ue_mu);

CREATE INDEX IF NOT EXISTS ix_pacientes_fecha      ON citas_pacientes(fecha);
CREATE INDEX IF NOT EXISTS ix_pacientes_medico     ON citas_pacientes(medico);
CREATE INDEX IF NOT EXISTS ix_pacientes_esp        ON citas_pacientes(especialidad);
CREATE INDEX IF NOT EXISTS ix_pacientes_cedula     ON citas_pacientes(cedula);
CREATE INDEX IF NOT EXISTS ix_pacientes_suc        ON citas_pacientes(cod_ue_mu);

CREATE INDEX IF NOT EXISTS ix_totales_fecha        ON citas_totales_dia(fecha);
CREATE INDEX IF NOT EXISTS ix_totales_suc          ON citas_totales_dia(cod_ue_mu);
"""


class DatabaseManager:
    """Fábrica de conexiones y punto único de acceso al esquema."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else settings.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- conexiones -------------------------------------------------------

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        """Abre una conexión. En modo readonly usa el URI file:...?mode=ro."""
        if readonly and self.db_path.exists():
            uri = f"file:{self.db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        else:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @contextmanager
    def cursor(self, *, readonly: bool = False) -> Iterator[sqlite3.Cursor]:
        """Context manager que abre conexión, entrega cursor y hace commit/cierre."""
        conn = self.connect(readonly=readonly)
        try:
            cur = conn.cursor()
            yield cur
            if not readonly:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- esquema ----------------------------------------------------------

    def init_schema(self) -> None:
        """Crea tablas e índices si no existen."""
        conn = self.connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def reset(self) -> None:
        """Borra todas las filas (usado por el ETL en modo full-reload)."""
        conn = self.connect()
        try:
            for table in (
                "citas_pacientes",
                "citas_medicos",
                "citas_totales_dia",
                "sucursales",
            ):
                conn.execute(f"DELETE FROM {table};")
            conn.commit()
        finally:
            conn.close()

    def table_counts(self) -> dict[str, int]:
        """Devuelve el número de filas por tabla (para el dashboard/healthcheck)."""
        counts: dict[str, int] = {}
        with self.cursor(readonly=True) as cur:
            for table in (
                "sucursales",
                "citas_medicos",
                "citas_pacientes",
                "citas_totales_dia",
            ):
                cur.execute(f"SELECT COUNT(*) AS n FROM {table};")
                counts[table] = cur.fetchone()["n"]
        return counts


# Instancia compartida por defecto.
db = DatabaseManager()
