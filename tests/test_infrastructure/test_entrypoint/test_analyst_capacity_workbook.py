from __future__ import annotations

from io import BytesIO

import openpyxl
import pytest

from src.infrastructure.entrypoint.worker.analyst_capacity_workbook import (
    parse_analyst_capacity_workbook,
)


def _workbook(profiles_rows: list[tuple], assignment_rows: list[tuple] | None = None) -> bytes:
    workbook = openpyxl.Workbook()
    profiles_sheet = workbook.active
    profiles_sheet.title = "Perfiles"
    profiles_sheet.append(["nombre", "descripción", *[str(h) for h in range(24)]])
    for row in profiles_rows:
        profiles_sheet.append(list(row))

    if assignment_rows is not None:
        assignments_sheet = workbook.create_sheet("Asignación")
        assignments_sheet.append(["día", "perfil"])
        for row in assignment_rows:
            assignments_sheet.append(list(row))

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_parses_profiles_and_day_assignments() -> None:
    content = _workbook(
        profiles_rows=[
            ("Día regular", "Cobertura estándar", *[4] * 24),
            ("Día de pago", "Refuerzo", *[8] * 24),
        ],
        assignment_rows=[(15, "Día de pago"), (20, "Día de pago"), (1, "Día regular")],
    )

    profiles, day_overrides = parse_analyst_capacity_workbook(content)

    assert [p.name for p in profiles] == ["Día regular", "Día de pago"]
    assert profiles[0].description == "Cobertura estándar"
    assert profiles[0].hourly == [4] * 24
    assert profiles[1].hourly == [8] * 24
    # every profile gets a fresh id, distinct from any existing config id
    assert profiles[0].id.startswith("imp-")
    assert profiles[0].id != profiles[1].id

    pago_id = profiles[1].id
    regular_id = profiles[0].id
    assert day_overrides == {15: pago_id, 20: pago_id, 1: regular_id}


def test_assignments_sheet_is_optional() -> None:
    content = _workbook(profiles_rows=[("Solo", "", *[4] * 24)])

    profiles, day_overrides = parse_analyst_capacity_workbook(content)

    assert len(profiles) == 1
    assert day_overrides == {}


def test_missing_profiles_sheet_raises() -> None:
    workbook = openpyxl.Workbook()
    workbook.active.title = "Hoja1"
    buffer = BytesIO()
    workbook.save(buffer)

    with pytest.raises(ValueError, match="Perfiles"):
        parse_analyst_capacity_workbook(buffer.getvalue())


def test_profile_with_short_header_raises() -> None:
    # openpyxl pads every data row to the sheet's max column width (set by
    # the header row) - so a genuinely too-few-columns case only shows up
    # when the header itself declares fewer than 24 hour columns, not when
    # a data row happens to have fewer values filled in (see the blank-cell
    # test below for that case).
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Perfiles"
    sheet.append(["nombre", "descripción", "0", "1", "2"])
    sheet.append(["Corto", "", 1, 2, 3])
    buffer = BytesIO()
    workbook.save(buffer)

    with pytest.raises(ValueError, match="24"):
        parse_analyst_capacity_workbook(buffer.getvalue())


def test_profile_with_blank_hour_cell_raises() -> None:
    rows = [4] * 24
    rows[5] = None
    content = _workbook(profiles_rows=[("Con hueco", "", *rows)])

    with pytest.raises(ValueError, match="fila 2"):
        parse_analyst_capacity_workbook(content)


def test_assignment_referencing_unknown_profile_raises() -> None:
    content = _workbook(
        profiles_rows=[("Día regular", "", *[4] * 24)],
        assignment_rows=[(15, "No existe")],
    )

    with pytest.raises(ValueError, match="No existe"):
        parse_analyst_capacity_workbook(content)


def test_assignment_day_out_of_range_raises() -> None:
    content = _workbook(
        profiles_rows=[("Día regular", "", *[4] * 24)],
        assignment_rows=[(45, "Día regular")],
    )

    with pytest.raises(ValueError, match="rango"):
        parse_analyst_capacity_workbook(content)


def test_no_profiles_raises() -> None:
    content = _workbook(profiles_rows=[])

    with pytest.raises(ValueError, match="Perfiles"):
        parse_analyst_capacity_workbook(content)


def test_garbage_content_raises_readable_error() -> None:
    with pytest.raises(ValueError, match="Excel"):
        parse_analyst_capacity_workbook(b"not an excel file")
