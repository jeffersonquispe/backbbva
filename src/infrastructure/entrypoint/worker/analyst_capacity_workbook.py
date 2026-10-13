from __future__ import annotations

from io import BytesIO
from typing import Any
from uuid import uuid4

import openpyxl

from src.domain.configurations.entities import (
    DayProfile,
)

# Two-sheet workbook: "Perfiles" defines named availability profiles (name,
# description, 24 hourly columns), "Asignación" maps day-of-month -> a
# profile name from the first sheet. Mirrors DayProfile/AnalystCapacity.
# day_overrides (application/ports/configuration_port.py) exactly, so the
# result plugs straight into the frontend's AnalystCapacityEditor.
PROFILES_SHEET = "Perfiles"
ASSIGNMENTS_SHEET = "Asignación"
HOUR_COLUMNS = 24


def parse_analyst_capacity_workbook(
    content: bytes,
) -> tuple[list[DayProfile], dict[int, str]]:
    try:
        workbook = openpyxl.load_workbook(BytesIO(content), data_only=True)
    except Exception as exc:
        raise ValueError(f"No se pudo leer el archivo Excel: {exc}") from exc

    profiles = _parse_profiles(workbook)
    day_overrides = _parse_assignments(workbook, profiles)
    return profiles, day_overrides


def _parse_profiles(workbook: Any) -> list[DayProfile]:
    if PROFILES_SHEET not in workbook.sheetnames:
        raise ValueError(
            f"Falta la hoja '{PROFILES_SHEET}' (columnas: nombre, "
            f"descripción, hora 0..23)."
        )
    sheet = workbook[PROFILES_SHEET]
    profiles: list[DayProfile] = []
    for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if not row or row[0] in (None, ""):
            continue
        name = str(row[0]).strip()
        description = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
        hourly_cells = row[2 : 2 + HOUR_COLUMNS]
        if len(hourly_cells) < HOUR_COLUMNS:
            raise ValueError(
                f"Hoja '{PROFILES_SHEET}', fila {index}: se esperaban "
                f"{HOUR_COLUMNS} columnas de hora (0-23)."
            )
        hourly = [_to_int(v, PROFILES_SHEET, index) for v in hourly_cells]
        profiles.append(
            DayProfile(
                id=f"imp-{uuid4().hex[:8]}",
                name=name,
                description=description,
                hourly=hourly,
            )
        )
    if not profiles:
        raise ValueError(f"Hoja '{PROFILES_SHEET}' no tiene perfiles.")
    return profiles


def _parse_assignments(workbook: Any, profiles: list[DayProfile]) -> dict[int, str]:
    if ASSIGNMENTS_SHEET not in workbook.sheetnames:
        return {}
    by_name = {p.name.strip().lower(): p.id for p in profiles}
    sheet = workbook[ASSIGNMENTS_SHEET]
    day_overrides: dict[int, str] = {}
    for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if not row or row[0] in (None, ""):
            continue
        day = _to_int(row[0], ASSIGNMENTS_SHEET, index)
        if not 1 <= day <= 31:
            raise ValueError(
                f"Hoja '{ASSIGNMENTS_SHEET}', fila {index}: día '{day}' "
                f"fuera de rango (1-31)."
            )
        profile_name = (
            str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
        )
        profile_id = by_name.get(profile_name.lower())
        if profile_id is None:
            raise ValueError(
                f"Hoja '{ASSIGNMENTS_SHEET}', fila {index}: perfil "
                f"'{profile_name}' no existe en '{PROFILES_SHEET}'."
            )
        day_overrides[day] = profile_id
    return day_overrides


def _to_int(value: Any, sheet_name: str, row_index: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Hoja '{sheet_name}', fila {row_index}: valor numérico "
            f"inválido '{value}'."
        ) from exc
