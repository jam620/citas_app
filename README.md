# Consulta de Citas — MVP

App web **de solo lectura** para consultar la información de 3 archivos CSV de
citas médicas (`citas_medicos.csv`, `citas_pacientes.csv`, `citas_totales_dia.csv`).

Stack: **Python 3.11+ · FastAPI · SQLite · Jinja2**. Sin login (app de prueba).

> ⚠️ **Los CSV reales NO se suben al repositorio** (contienen datos personales
> sensibles). Colócalos en `data/` o genera una muestra sintética con
> `python scripts/make_sample_data.py`. Ver `.gitignore` y `MEMORIA.md`.

## Puesta en marcha

```bash
# 1. Dependencias
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2a. Con los CSV reales: colócalos en data/
# 2b. Sin CSV reales: genera una muestra sintética
python scripts/make_sample_data.py data

# 3. Carga los CSV a SQLite
python -m app.etl data

# 4. Arranca el servidor
uvicorn app.main:app --reload
#    -> http://127.0.0.1:8000        (interfaz)
#    -> http://127.0.0.1:8000/docs   (API)

# 5. Pruebas
pytest -q
```

## Qué puedes consultar

| Vista | Contenido | Extras |
|---|---|---|
| `/` (Inicio) | Dashboard: totales, pacientes únicos, top especialidades, citas por sucursal y por mes | gráficos de barras sin JS |
| `/pacientes` | Citas por nombre, cédula, médico, especialidad, sucursal y rango de fechas | orden por columna, export CSV |
| `/medicos` | Cupos por médico y día | orden por columna, export CSV |
| `/totales` | Citas totales por día (resumen pre-agregado) | orden por columna, export CSV |

## API JSON

- `GET /api/health` — estado + conteo de filas por tabla.
- `GET /api/resumen` — métricas generales.
- `GET /api/pacientes | /api/medicos | /api/totales` — consulta paginada con
  filtros, `sort`, `direction` (`asc`/`desc`), `page` y `page_size`.
- `GET /pacientes/export | /medicos/export | /totales/export` — los mismos
  filtros de la vista, respuesta CSV en streaming con tope de filas
  (`CITAS_MAX_EXPORT_ROWS`, default 100 000).

## Documentación

| Doc | Contenido |
|---|---|
| `MEMORIA.md` | **Memoria del proyecto**: análisis, decisiones, estado actual |
| `00_MASTER_PROMPT.md` … `08_TESTING.md` | Diseño original módulo por módulo |

## Notas

- Los 3 CSV tienen formatos de fecha distintos y codificación no siempre
  UTF-8; el ETL (`app/etl.py`) los normaliza a ISO y decodifica todo el archivo
  antes de insertar (carga all-or-nothing por tabla, en lotes de 20 000 filas).
- `paciente + cédula + especialidad` es dato sensible de salud. El MVP lo
  muestra completo por decisión explícita; ver la sección de seguridad en
  `00_MASTER_PROMPT.md` antes de llevarlo a un entorno real.
