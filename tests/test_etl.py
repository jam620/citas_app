"""Pruebas del ETL: fechas, encoding, nombres sucios, idempotencia."""
from __future__ import annotations

from pathlib import Path

from app.database import DatabaseManager
from app.etl import ETLImporter, parse_fecha_dmy, parse_fecha_mes_dia, normalize_medico, clean_text


def test_parse_fecha_dmy():
    assert parse_fecha_dmy("1-10-2025") == "2025-10-01"
    assert parse_fecha_dmy("15-1-2026") == "2026-01-15"


def test_parse_fecha_mes_dia():
    assert parse_fecha_mes_dia("2026-10", "1") == "2026-10-01"
    assert parse_fecha_mes_dia("2026-10", "26") == "2026-10-26"


def test_clean_text_quita_saltos():
    assert clean_text("FLORES\nMURILLO") == "FLORES MURILLO"
    assert clean_text("  dos   espacios  ") == "dos espacios"


def test_normalize_medico_mayusculas():
    assert normalize_medico("Licda. Patterson Hany") == "LICDA. PATTERSON HANY"


def test_carga_basica(loaded: DatabaseManager):
    counts = loaded.table_counts()
    assert counts["citas_medicos"] == 3
    assert counts["citas_pacientes"] == 3
    assert counts["citas_totales_dia"] == 2
    # Dos sucursales distintas.
    assert counts["sucursales"] == 2


def test_idempotencia(database: DatabaseManager, data_dir: Path):
    importer = ETLImporter(database)
    importer.run(data_dir)
    importer.run(data_dir)  # segunda corrida, full_reload por defecto
    assert database.table_counts()["citas_pacientes"] == 3


def test_coma_embebida_en_nombre(loaded: DatabaseManager):
    with loaded.cursor(readonly=True) as cur:
        cur.execute("SELECT medico FROM citas_medicos WHERE medico LIKE '%SAMUDIO%';")
        row = cur.fetchone()
    assert row is not None
    assert "SAMUDIO" in row["medico"] and "PATRICIA" in row["medico"]


def test_cedula_es_texto(loaded: DatabaseManager):
    with loaded.cursor(readonly=True) as cur:
        cur.execute("SELECT cedula FROM citas_pacientes WHERE cedula = 'AT652430';")
        assert cur.fetchone() is not None


def test_encoding_fallback_cp1252(database: DatabaseManager, tmp_path: Path):
    """Un archivo cp1252 con Ñ debe leerse sin romperse."""
    d = tmp_path / "cp"
    d.mkdir()
    (d / "citas_medicos.csv").write_text(
        "cod_ue_mu,sucursal,fecha,medico,total_cupos\n"
        "1,Suc Ñandú,1-10-2025,DR. NUÑEZ,3\n",
        encoding="cp1252",
    )
    (d / "citas_pacientes.csv").write_bytes(
        "cod_ue_mu,sucursal,fecha,hora,medico,especialidad,paciente,cedula\n".encode("cp1252")
    )
    (d / "citas_totales_dia.csv").write_text(
        "cod_ue_mu,sucursal,mes,dia,total_citas\n1,Suc Ñandú,2026-10,1,5\n",
        encoding="cp1252",
    )
    ETLImporter(database).run(d)
    with database.cursor(readonly=True) as cur:
        cur.execute("SELECT medico FROM citas_medicos;")
        assert cur.fetchone()["medico"] == "DR. NUÑEZ"
