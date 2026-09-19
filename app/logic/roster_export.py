"""Shapes Assignment/Staff data into per-day roster rows for the monthly
duty-roster Word export (see app/docx_export.py), split by co so and further
split by trinh_do (Dai hoc/Cao dang) x shift length (24/24 vs 12/24).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from app.config import WEEKDAY_LABELS
from app.logic.calendar_rules import (
    DUTY_CODE_HOLIDAY,
    DUTY_CODE_SATURDAY,
    DUTY_CODE_SUNDAY,
    resolve_day_type,
)
from app.logic.types import AssignmentRecord, HolidayRule, StaffInfo

NAME_SEPARATOR = ";\n"

# Config here -- fill for a roster row whose day is a Saturday, Sunday or
# holiday (same day-type definition calendar_rules.resolve_day_type uses for
# duty weights, where a holiday wins over the weekday).
OFF_DAY_ROW_SHADING = "#D9D9D9"
_OFF_DAY_CODES = (DUTY_CODE_SATURDAY, DUTY_CODE_SUNDAY, DUTY_CODE_HOLIDAY)

_TRINH_DO_DAI_HOC = "Đại học"
_TRINH_DO_CAO_DANG = "Cao đẳng"


@dataclass(frozen=True)
class RosterRow:
    day: date
    weekday_label: str
    dai_hoc_24: str = ""
    dai_hoc_12: str = ""
    cao_dang_24: str = ""
    cao_dang_12: str = ""
    ghi_chu: str = ""
    shading: str | None = None  # hex fill for the whole row, e.g. "#D9D9D9"


def _roster_name(staff: StaffInfo) -> str:
    """"Nguyễn Thị Thu (Nhà thuốc K1)": the name is title-cased, but vi_tri
    is printed exactly as stored (title-casing would turn "K1" into "k1")."""
    name = staff.ho_va_ten.title()
    return f"{name} ({staff.vi_tri})" if staff.vi_tri else name


def build_roster_rows(
    assignments: list[AssignmentRecord],
    staff_by_id: dict[str, StaffInfo],
    base: str,
    year: int,
    month: int,
    holidays: list[HolidayRule] | None = None,
) -> list[RosterRow]:
    """One RosterRow per calendar day of `year`/`month`, populated from every
    assignment at `base` on that day. A staff_id missing from `staff_by_id`,
    or a trinh_do outside Dai hoc/Cao dang, is silently skipped rather than
    raising -- the roster should still render for the rest of the month even
    if one row of staff data is incomplete/dirty.

    Rows for a Saturday, Sunday or a day in `holidays` carry
    OFF_DAY_ROW_SHADING so the Word table can grey them out.
    """
    holidays = holidays or []
    names_by_day: dict[date, dict[str, list[str]]] = {}
    for a in assignments:
        if a.base != base:
            continue
        staff = staff_by_id.get(a.staff_id)
        if staff is None or staff.trinh_do not in (_TRINH_DO_DAI_HOC, _TRINH_DO_CAO_DANG):
            continue
        bucket = "dai_hoc" if staff.trinh_do == _TRINH_DO_DAI_HOC else "cao_dang"
        shift = "12" if a.is_half_day else "24"
        key = f"{bucket}_{shift}"
        names_by_day.setdefault(a.duty_date, {}).setdefault(key, []).append(_roster_name(staff))

    last_day = calendar.monthrange(year, month)[1]
    rows = []
    for day_num in range(1, last_day + 1):
        day = date(year, month, day_num)
        cells = names_by_day.get(day, {})
        rows.append(
            RosterRow(
                day=day,
                weekday_label=WEEKDAY_LABELS[day.weekday()],
                dai_hoc_24=NAME_SEPARATOR.join(cells.get("dai_hoc_24", [])),
                dai_hoc_12=NAME_SEPARATOR.join(cells.get("dai_hoc_12", [])),
                cao_dang_24=NAME_SEPARATOR.join(cells.get("cao_dang_24", [])),
                cao_dang_12=NAME_SEPARATOR.join(cells.get("cao_dang_12", [])),
                shading=OFF_DAY_ROW_SHADING if resolve_day_type(day, holidays) in _OFF_DAY_CODES else None,
            )
        )
    return rows
