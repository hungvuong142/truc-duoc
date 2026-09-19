"""Excel import/export of duty assignments (framework-agnostic).

One row per (date, base). The 24/24 and 12/24 staff of that slot are
delimited cells ("12262 - CHU HOÀNG BÍCH HỒNG; 34015 - ĐẶNG MINH ĐỨC"; only
the code before " - " is read back, so a bare "12262" works too), plus a
third list marking which of them are DSĐH covering a Cao đẳng slot.

Importing replaces a slot wholesale when the file mentions it, adds slots the
app doesn't have yet, and leaves every other slot alone.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from app.config import BASE_LABELS, BASE_SHORT_LABELS, BASES
from app.logic.types import AssignmentRecord, StaffInfo

COL_DATE = "ngay"
COL_BASE = "co_so"
COL_FULL = "ds_truc_24"
COL_HALF = "ds_truc_12"
COL_COVER = "ds_dsdh_truc_cao_dang"
COLUMNS = [COL_DATE, COL_BASE, COL_FULL, COL_HALF, COL_COVER]

STATUS_NEW = "new"
STATUS_OVERRIDE = "override"
STATUS_UNCHANGED = "unchanged"

_LIST_SPLIT = re.compile(r"[;,\n]")
_BASE_ORDER = {base: i for i, base in enumerate(BASES)}
_BASE_BY_ALIAS = {
    alias.strip().casefold(): base
    for base in BASES
    for alias in (base, BASE_LABELS[base], BASE_SHORT_LABELS[base])
}


@dataclass(frozen=True)
class SlotEntry:
    staff_id: str
    is_half_day: bool = False
    is_cao_dang_cover: bool = False


@dataclass(frozen=True)
class SlotPlan:
    duty_date: date
    base: str
    entries: tuple[SlotEntry, ...]
    status: str
    existing_count: int


@dataclass
class ParsedImport:
    slots: dict[tuple[date, str], tuple[SlotEntry, ...]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    blank_rows: int = 0


def normalize_base(value) -> str | None:
    if pd.isna(value):
        return None
    return _BASE_BY_ALIAS.get(str(value).strip().casefold())


def normalize_staff_id(text: str) -> str:
    """Excel drops leading zeros from numeric-looking cells; re-pad to the
    4-digit convention (same rule as repository._normalize_bmo_id)."""
    text = text.strip()
    return f"{int(text):04d}" if text.isdigit() else text


def _parse_date(raw) -> pd.Timestamp:
    """ISO dates (what Excel/our export produce) first, then day-first text
    like "19/09/2026"."""
    text = str(raw).strip()
    parsed = pd.to_datetime(text, format="ISO8601", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    return parsed


def parse_staff_cell(value) -> list[str]:
    if pd.isna(value):
        return []
    ids: list[str] = []
    for token in _LIST_SPLIT.split(str(value)):
        staff_id = normalize_staff_id(token.split(" - ")[0])
        if staff_id and staff_id not in ids:
            ids.append(staff_id)
    return ids


def _format_staff_cell(staff_ids: list[str], staff_by_id: dict[str, StaffInfo]) -> str:
    return "; ".join(
        f"{i} - {staff_by_id[i].ho_va_ten}" if i in staff_by_id else i for i in staff_ids
    )


def build_export_rows(assignments: list[AssignmentRecord], staff_by_id: dict[str, StaffInfo]) -> list[dict]:
    slots: dict[tuple[date, str], list[AssignmentRecord]] = defaultdict(list)
    for a in assignments:
        slots[(a.duty_date, a.base)].append(a)

    def staff_order(a: AssignmentRecord) -> tuple:
        staff = staff_by_id.get(a.staff_id)
        is_dai_hoc = staff is not None and staff.trinh_do == "Đại học" and not a.is_cao_dang_cover
        return (0 if is_dai_hoc else 1, staff.ho_va_ten if staff else a.staff_id)

    rows = []
    for duty_date, base in sorted(slots, key=lambda k: (k[0], _BASE_ORDER.get(k[1], len(BASES)))):
        entries = sorted(slots[(duty_date, base)], key=staff_order)
        rows.append({
            COL_DATE: duty_date,
            COL_BASE: BASE_SHORT_LABELS.get(base, base),
            COL_FULL: _format_staff_cell([a.staff_id for a in entries if not a.is_half_day], staff_by_id),
            COL_HALF: _format_staff_cell([a.staff_id for a in entries if a.is_half_day], staff_by_id),
            COL_COVER: _format_staff_cell([a.staff_id for a in entries if a.is_cao_dang_cover], staff_by_id),
        })
    return rows


def parse_import_frame(df: pd.DataFrame, valid_staff_ids: set[str]) -> ParsedImport:
    """Parse and validate an uploaded sheet. Cells are expected as text
    (read the file with dtype=str). Any problem is collected in `errors`
    (with its Excel row number); the caller must not apply a parse that has
    errors."""
    result = ParsedImport()
    first_line_of: dict[tuple[date, str], int] = {}

    for position, row in enumerate(df.to_dict("records")):
        line = position + 2  # header is row 1
        if all(pd.isna(v) for v in row.values()):
            continue

        problems: list[str] = []
        raw_date = row.get(COL_DATE)
        duty_date = None
        if pd.isna(raw_date):
            problems.append("thiếu ngày")
        else:
            parsed = _parse_date(raw_date)
            if pd.isna(parsed):
                problems.append(f"ngày không hợp lệ ({raw_date})")
            else:
                duty_date = parsed.date()

        base = normalize_base(row.get(COL_BASE))
        if base is None:
            problems.append("cơ sở phải là CSHN hoặc CSNB")

        full_ids = parse_staff_cell(row.get(COL_FULL))
        half_ids = parse_staff_cell(row.get(COL_HALF))
        cover_ids = parse_staff_cell(row.get(COL_COVER))

        both = [i for i in full_ids if i in half_ids]
        if both:
            problems.append(f"nhân viên vừa trực 24/24 vừa 12/24: {', '.join(both)}")
        unknown = [i for i in dict.fromkeys(full_ids + half_ids + cover_ids) if i not in valid_staff_ids]
        if unknown:
            problems.append(f"không tìm thấy mã nhân viên: {', '.join(unknown)}")
        stray_cover = [i for i in cover_ids if i not in full_ids and i not in half_ids]
        if stray_cover:
            problems.append(f"DSĐH trực vị trí cao đẳng nhưng không có trong DS trực: {', '.join(stray_cover)}")

        if not problems and not full_ids and not half_ids:
            result.blank_rows += 1
            continue

        if duty_date is not None and base is not None:
            key = (duty_date, base)
            if key in first_line_of:
                problems.append(f"trùng ngày + cơ sở với dòng {first_line_of[key]}")
            else:
                first_line_of[key] = line

        if problems:
            result.errors.append(f"Dòng {line}: " + "; ".join(problems))
            continue

        result.slots[(duty_date, base)] = tuple(
            SlotEntry(i, is_half_day=i in half_ids, is_cao_dang_cover=i in cover_ids)
            for i in full_ids + half_ids
        )
    return result


def plan_import(
    slots: dict[tuple[date, str], tuple[SlotEntry, ...]],
    existing: list[AssignmentRecord],
    staff_names: dict[str, str] | None = None,
) -> tuple[list[SlotPlan], list[str]]:
    """Compare parsed slots with what's already stored. A slot the file
    mentions is `new`, `override` (stored content differs) or `unchanged`.
    Also rejects a result in which a staff member would work both bases on
    one date -- the same rule the calendar's assign dialog enforces."""
    names = staff_names or {}
    existing_by_slot: dict[tuple[date, str], set[SlotEntry]] = defaultdict(set)
    for a in existing:
        existing_by_slot[(a.duty_date, a.base)].add(
            SlotEntry(a.staff_id, a.is_half_day, a.is_cao_dang_cover)
        )

    plans = []
    for (duty_date, base), entries in slots.items():
        stored = existing_by_slot.get((duty_date, base), set())
        if not stored:
            status = STATUS_NEW
        elif stored == set(entries):
            status = STATUS_UNCHANGED
        else:
            status = STATUS_OVERRIDE
        plans.append(SlotPlan(duty_date, base, entries, status, len(stored)))
    plans.sort(key=lambda p: (p.duty_date, _BASE_ORDER.get(p.base, len(BASES))))

    bases_worked: dict[tuple[date, str], set[str]] = defaultdict(set)
    file_dates = {duty_date for duty_date, _ in slots}
    for (duty_date, base), stored in existing_by_slot.items():
        if duty_date in file_dates and (duty_date, base) not in slots:
            for entry in stored:
                bases_worked[(duty_date, entry.staff_id)].add(base)
    for (duty_date, base), entries in slots.items():
        for entry in entries:
            bases_worked[(duty_date, entry.staff_id)].add(base)

    errors = [
        f"{staff_id}{f' ({names[staff_id]})' if staff_id in names else ''} bị phân trực cả hai cơ sở "
        f"ngày {duty_date.strftime('%d/%m/%Y')} (kể cả phần dữ liệu hiện có không nằm trong file)"
        for (duty_date, staff_id), bases in sorted(bases_worked.items())
        if len(bases) > 1
    ]
    return plans, errors
