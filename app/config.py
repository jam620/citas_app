"""
Configuración central del MVP.

Lee variables de entorno (opcionalmente desde un archivo .env si existe) y las
expone como un objeto `settings` inmutable. No hay secretos aquí porque el MVP
no tiene autenticación; aun así centralizamos las rutas para no tener strings
mágicos dispersos por el código.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Cargador .env mínimo (sin dependencias externas)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # No sobreescribimos lo que ya venga del entorno real.
        os.environ.setdefault(key, value)


# Raíz del proyecto = carpeta que contiene a /app
BASE_DIR = Path(__file__).resolve().parent.parent
_load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    data_dir: Path
    db_path: Path
    max_page_size: int
    default_page_size: int
    debug: bool

    # Nombres de archivo esperados de los 3 CSV de origen.
    csv_medicos: str = "citas_medicos.csv"
    csv_pacientes: str = "citas_pacientes.csv"
    csv_totales: str = "citas_totales_dia.csv"


def _build_settings() -> Settings:
    data_dir = (BASE_DIR / _env("CITAS_DATA_DIR", "data")).resolve()
    db_path = Path(_env("CITAS_DB_PATH", str(data_dir / "citas.db")))
    if not db_path.is_absolute():
        db_path = (BASE_DIR / db_path).resolve()

    max_page = max(1, int(_env("CITAS_MAX_PAGE_SIZE", "200")))
    return Settings(
        base_dir=BASE_DIR,
        data_dir=data_dir,
        db_path=db_path,
        max_page_size=max_page,
        default_page_size=min(50, max_page),
        debug=_env("CITAS_DEBUG", "false").lower() in {"1", "true", "yes"},
    )


settings = _build_settings()
