"""
Genera los 3 CSV de MUESTRA (datos 100% sintéticos) en la carpeta data/.

Los CSV reales NUNCA se suben al repositorio (contienen datos personales
sensibles). Este script permite que un clon fresco pueda correr el ETL, las
pruebas y la app sin tener los archivos reales.

Uso:
    python scripts/make_sample_data.py [carpeta_destino]   # default: data
"""
from __future__ import annotations

import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

random.seed(42)  # muestra reproducible

SUCURSALES = [
    (1, "Policlínica Generoso Guardia (Santa Librada)"),
    (2, "Policlínica Manuel Ferrer Valdes (Calle 25)"),
    (3, "Policlínica Manuel Maria Valdes (San Miguelito)"),
]

ESPECIALIDADES = [
    "Medicina General", "Pediatria", "Odontologia", "Gineco-Obstetricia",
    "Medicina Interna", "Oftalmología", "Psicologia", "Urologia",
]

NOMBRES = [
    "MARIA", "JOSE", "LUIS", "CARLOS", "ANA", "JOSEPH", "SOFIA", "DIEGO",
    "CARMEN", "ROBERTO", "YANELIS", "ARISTIDES", "KELLY", "EDGARDO",
]
APELLIDOS = [
    "PEREZ", "RODRIGUEZ", "CEDEÑO", "GONZALEZ", "MURILLO", "QUIJADA",
    "SANCHEZ", "GUTIERREZ", "FLORES", "VASQUEZ", "NUNEZ", "PEÑA",
]
TITULOS = ["DR.", "DRA.", "LIC.", "LICDA."]

MESES = 3          # meses de datos
DIAS_HABILES = 20  # días por mes


def _fecha_aleatoria() -> date:
    hoy = date.today().replace(day=1)
    mes_ini = hoy
    dia = random.randint(1, 28)
    mes_off = random.randint(0, MESES - 1)
    y = mes_ini.year + (mes_ini.month - 1 + mes_off) // 12
    m = (mes_ini.month - 1 + mes_off) % 12 + 1
    return date(y, m, dia)


def _nombre_persona() -> str:
    return f"{random.choice(NOMBRES)} {random.choice(APELLIDOS)} {random.choice(APELLIDOS)}"


def _cedula() -> str:
    return f"{random.choice('123489')}-{random.randint(10, 9999)}-{random.randint(100, 999)}"


def main(destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)

    # --- medicos: un registro de cupos por médico/día/sucursal --------------
    medicos: dict[tuple[int, str], str] = {}
    for cod, _suc in SUCURSALES:
        for _ in range(6):
            medicos[(cod, f"{random.choice(TITULOS)} {_nombre_persona()}")] = random.choice(ESPECIALIDADES)

    filas_medicos = []
    filas_pacientes = []
    filas_totales = []

    for mes_off in range(MESES):
        base = date.today().replace(day=1)
        y = base.year + (base.month - 1 + mes_off) // 12
        m = (base.month - 1 + mes_off) % 12 + 1
        for dia in range(1, DIAS_HABILES + 1):
            try:
                f = date(y, m, dia)
            except ValueError:
                continue
            total_dia = 0
            for (cod, medico), especialidad in medicos.items():
                if random.random() < 0.35:  # no todos trabajan todos los días
                    continue
                cupos = random.randint(1, 15)
                filas_medicos.append(
                    [str(cod), SUCURSALES[cod - 1][1], f"{f.day}-{f.month}-{f.year}",
                     medico, str(cupos)]
                )
                for hora_i in range(cupos):
                    hora = f"{random.randint(7, 16):02d}:{random.choice(['00', '20', '30', '40'])}:00"
                    paciente = _nombre_persona()
                    cedula = _cedula()
                    filas_pacientes.append(
                        [str(cod), SUCURSALES[cod - 1][1], f"{f.day}-{f.month}-{f.year}",
                         hora, medico, especialidad, paciente, cedula]
                    )
                    total_dia += 1
            if total_dia:
                filas_totales.append(
                    [str(SUCURSALES[0][0] - 1 + 1), SUCURSALES[0][1],
                     f"{y}-{m:02d}", str(dia), str(total_dia)]
                )

    # Totales por sucursal/día = conteo de pacientes generados ese día.
    por_dia: dict[tuple[int, str, str, str], int] = {}
    for f_pac in filas_pacientes:
        d, m, y = f_pac[2].split("-")
        key = (int(f_pac[0]), f_pac[1], f"{y}-{int(m):02d}", d)
        por_dia[key] = por_dia.get(key, 0) + 1
    for (cod, suc, mes, dia), total in sorted(por_dia.items()):
        filas_totales.append([str(cod), suc, mes, dia, str(total)])

    _escribir(destino / "citas_medicos.csv",
              ["cod_ue_mu", "sucursal", "fecha", "medico", "total_cupos"], filas_medicos)
    _escribir(destino / "citas_pacientes.csv",
              ["cod_ue_mu", "sucursal", "fecha", "hora", "medico", "especialidad",
               "paciente", "cedula"], filas_pacientes)
    _escribir(destino / "citas_totales_dia.csv",
              ["cod_ue_mu", "sucursal", "mes", "dia", "total_citas"], filas_totales)

    print(f"Muestra generada en {destino}:")
    print(f"  - citas_medicos.csv:      {len(filas_medicos)} filas")
    print(f"  - citas_pacientes.csv:    {len(filas_pacientes)} filas")
    print(f"  - citas_totales_dia.csv:  {len(filas_totales)} filas")


def _escribir(path: Path, headers: list[str], filas: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(filas)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")
    main(target)
