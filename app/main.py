"""
Punto de entrada FastAPI.

Arranque:
    uvicorn app.main:app --reload

Cabeceras de seguridad básicas añadidas por middleware. Debug desactivado por
defecto para no filtrar trazas de error al cliente.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import VERSION
from .config import settings
from .database import db
from .routes import router

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Garantiza que el esquema exista (no importa datos; eso lo hace el ETL).
    db.init_schema()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Consulta de Citas",
        description="MVP de solo lectura para consultar los CSV de citas.",
        version=VERSION,
        debug=settings.debug,
        lifespan=lifespan,
    )

    static_dir = Path(__file__).parent.parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        # La app no usa JS inline ni recursos externos: CSP estricta y simple.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'"
        )
        return response

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # No exponemos la traza al cliente salvo en modo debug.
        if settings.debug:
            raise exc
        return JSONResponse(status_code=500, content={"detail": "Error interno."})

    return app


app = create_app()
