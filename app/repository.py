"""DB-facing functions the UI calls: DataFrame <-> ORM <-> logic dataclass
conversions. This is the only layer that talks to SQLAlchemy sessions;
`app/logic/` never imports from here.
"""

from __future__ import annotations

import calendar
from datetime import date

import pandas as pd
import streamlit as st
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.db import get_readonly_session, get_session
from app.logic.types import AssignmentRecord, DutyWeightRule, HolidayRule, StaffInfo
from app.models import Assignment, DutyWeight, Holiday, NinhBinhAssignment, Staff

# Staff/duty-weights/holidays change only through explicit edits in the Data
# tab (rare) but are re-read on almost every rerun (calendar, stats, every
# dialog). Caching them cuts a Postgres round trip (~150-350ms each over the
# network, vs microseconds for the old local SQLite file) down to zero on
# unrelated reruns. Every write path below calls `.clear()` on the relevant
# cached getter so edits show up immediately; the short TTL is only a
# safety net for data changed outside the app (e.g. direct SQL).
_CACHE_TTL_SECONDS = 300


def _normalize_bmo_id(value) -> str:
    """Excel drops leading zeros from a cell like "0001" once it's treated
    as a number, so a re-uploaded/edited template can come back as the bare
    int 1. Zero-pad it back to the 4-digit convention so it still matches
    the existing staff row instead of creating a duplicate."""
    text = str(value).strip()
    if text.isdigit():
        return f"{int(text):04d}"
    return text


def _normalize_phone(value) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if text.replace(".", "", 1).isdigit() and "." in text:
        text = str(int(float(text)))  # Excel may store it as a float too
    if text.isdigit() and len(text) == 9:
        text = "0" + text
    return text


def _to_bool(value, default: bool = False) -> bool:
    """Coerce a value coming from an uploaded spreadsheet (which may hold a
    real bool, 1/0, or a string like "TRUE"/"Có"/"x") into a bool."""
    if pd.isna(value):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("true", "1", "yes", "y", "x", "có", "co")


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

STAFF_COLUMNS = [
    "bmo_id", "ho_va_ten", "tuoi", "gioi_tinh", "trinh_do", "vi_tri",
    "so_dien_thoai", "mang_thai", "sinh_de", "ghi_chu", "ninh_binh_base",
    "is_active",
]


@st.cache_data(ttl=_CACHE_TTL_SECONDS)
def get_staff_df(active_only: bool = False) -> pd.DataFrame:
    with get_readonly_session() as session:
        stmt = select(Staff)
        if active_only:
            stmt = stmt.where(Staff.is_active.is_(True))
        rows = session.scalars(stmt).all()
        data = [{col: getattr(r, col) for col in STAFF_COLUMNS} for r in rows]
    df = pd.DataFrame(data, columns=STAFF_COLUMNS)
    if df.empty:
        return df
    df["mang_thai"] = df["mang_thai"].astype(bool)
    df["sinh_de"] = df["sinh_de"].astype(bool)
    df["ninh_binh_base"] = df["ninh_binh_base"].astype(bool)
    df["is_active"] = df["is_active"].astype(bool)
    return df


def _next_staff_id(existing_ids: list[str]) -> str:
    numeric = [int(i) for i in existing_ids if i.isdigit()]
    return f"{(max(numeric) + 1) if numeric else 1:04d}"


def upsert_staff_df(df: pd.DataFrame) -> None:
    """Full sync: rows in `df` are upserted, rows missing from `df` (but
    present in the DB) are deleted. Blank/new bmo_id values are assigned
    the next free id."""
    with get_session() as session:
        existing_ids = [s.bmo_id for s in session.scalars(select(Staff)).all()]
        seen_ids: set[str] = set()

        for _, row in df.iterrows():
            bmo_id = str(row["bmo_id"]).strip() if pd.notna(row.get("bmo_id")) else ""
            if not bmo_id:
                bmo_id = _next_staff_id(existing_ids)
                existing_ids.append(bmo_id)

            staff = session.get(Staff, bmo_id)
            if staff is None:
                staff = Staff(bmo_id=bmo_id)
                session.add(staff)

            staff.ho_va_ten = str(row["ho_va_ten"]).strip()
            staff.tuoi = int(row["tuoi"]) if pd.notna(row.get("tuoi")) else None
            staff.gioi_tinh = row.get("gioi_tinh") or None
            staff.trinh_do = row.get("trinh_do") or None
            staff.vi_tri = str(row["vi_tri"]).strip()
            staff.so_dien_thoai = str(row["so_dien_thoai"]) if pd.notna(row.get("so_dien_thoai")) else None
            staff.mang_thai = bool(row.get("mang_thai", False))
            staff.sinh_de = bool(row.get("sinh_de", False))
            staff.ghi_chu = row.get("ghi_chu") or None
            staff.ninh_binh_base = bool(row.get("ninh_binh_base", False))
            staff.is_active = bool(row.get("is_active", True))
            seen_ids.add(bmo_id)

        for stale_id in set(existing_ids) - seen_ids:
            stale = session.get(Staff, stale_id)
            if stale is not None:
                session.delete(stale)
    get_staff_df.clear()
    get_all_staff.clear()


def import_staff_df(df: pd.DataFrame) -> int:
    """Upsert rows from an uploaded spreadsheet by bmo_id, without deleting
    any existing staff not present in the file (additive, unlike the
    data-editor's full-sync save)."""
    count = 0
    with get_session() as session:
        existing_ids = [s.bmo_id for s in session.scalars(select(Staff)).all()]

        for _, row in df.iterrows():
            bmo_id = _normalize_bmo_id(row["bmo_id"]) if pd.notna(row.get("bmo_id")) else ""
            if not bmo_id:
                bmo_id = _next_staff_id(existing_ids)
                existing_ids.append(bmo_id)

            staff = session.get(Staff, bmo_id)
            if staff is None:
                staff = Staff(bmo_id=bmo_id)
                session.add(staff)

            staff.ho_va_ten = str(row["ho_va_ten"]).strip()
            staff.tuoi = int(row["tuoi"]) if pd.notna(row.get("tuoi")) else None
            staff.gioi_tinh = row.get("gioi_tinh") or None
            staff.trinh_do = row.get("trinh_do") or None
            staff.vi_tri = str(row["vi_tri"]).strip()
            staff.so_dien_thoai = _normalize_phone(row.get("so_dien_thoai"))
            staff.mang_thai = _to_bool(row.get("mang_thai"))
            staff.sinh_de = _to_bool(row.get("sinh_de"))
            staff.ghi_chu = row.get("ghi_chu") or None
            staff.ninh_binh_base = _to_bool(row.get("ninh_binh_base"))
            staff.is_active = _to_bool(row.get("is_active"), default=True)
            count += 1
    get_staff_df.clear()
    get_all_staff.clear()
    return count


@st.cache_data(ttl=_CACHE_TTL_SECONDS)
def get_all_staff(active_only: bool = True) -> list[StaffInfo]:
    with get_readonly_session() as session:
        stmt = select(Staff)
        if active_only:
            stmt = stmt.where(Staff.is_active.is_(True))
        rows = session.scalars(stmt).all()
        return [
            StaffInfo(
                bmo_id=r.bmo_id, ho_va_ten=r.ho_va_ten, gioi_tinh=r.gioi_tinh,
                trinh_do=r.trinh_do, vi_tri=r.vi_tri, so_dien_thoai=r.so_dien_thoai,
                mang_thai=r.mang_thai, sinh_de=r.sinh_de, ghi_chu=r.ghi_chu,
                ninh_binh_base=r.ninh_binh_base, is_active=r.is_active,
            )
            for r in rows
        ]


def get_all_staff_by_id(active_only: bool = False) -> dict[str, StaffInfo]:
    return {s.bmo_id: s for s in get_all_staff(active_only=active_only)}


# ---------------------------------------------------------------------------
# Ninh Binh base assignment (per staff, per month) -- Staff.ninh_binh_base is
# a derived snapshot of this table, recomputed by sync_ninh_binh_base.
# ---------------------------------------------------------------------------

@st.cache_data(ttl=_CACHE_TTL_SECONDS)
def get_ninh_binh_assignments_df(year: int, month: int) -> pd.DataFrame:
    """Active staff with a checkbox for whether they're marked to go to the
    Ninh Binh base for this specific (year, month)."""
    with get_readonly_session() as session:
        staff_rows = session.scalars(
            select(Staff).where(Staff.is_active.is_(True)).order_by(Staff.ho_va_ten)
        ).all()
        assigned_ids = set(session.scalars(
            select(NinhBinhAssignment.staff_id).where(
                NinhBinhAssignment.year == year, NinhBinhAssignment.month == month
            )
        ).all())
        data = [
            {
                "bmo_id": s.bmo_id, "ho_va_ten": s.ho_va_ten, "trinh_do": s.trinh_do,
                "vi_tri": s.vi_tri, "di_ninh_binh": s.bmo_id in assigned_ids,
            }
            for s in staff_rows
        ]
    return pd.DataFrame(data, columns=["bmo_id", "ho_va_ten", "trinh_do", "vi_tri", "di_ninh_binh"])


def save_ninh_binh_assignments(year: int, month: int, staff_ids: list[str]) -> None:
    """Full sync for one (year, month): `staff_ids` is the exact set of
    staff checked to go to the Ninh Binh base that month. Also recomputes
    Staff.ninh_binh_base immediately so the "Nhân viên" sheet reflects the
    change without waiting for the next app restart."""
    with get_session() as session:
        existing = session.scalars(
            select(NinhBinhAssignment).where(
                NinhBinhAssignment.year == year, NinhBinhAssignment.month == month
            )
        ).all()
        existing_by_staff = {row.staff_id: row for row in existing}
        wanted = set(staff_ids)

        for staff_id in wanted - existing_by_staff.keys():
            session.add(NinhBinhAssignment(staff_id=staff_id, year=year, month=month))
        for staff_id, row in existing_by_staff.items():
            if staff_id not in wanted:
                session.delete(row)
    get_ninh_binh_assignments_df.clear()
    get_ninh_binh_assignment_months.clear()
    sync_ninh_binh_base()


def sync_ninh_binh_base(reference_date: date | None = None) -> None:
    """Recompute Staff.ninh_binh_base from ninh_binh_assignments: True for
    staff with a row matching the reference (year, month) -- defaulting to
    today -- False otherwise."""
    ref = reference_date or date.today()
    with get_session() as session:
        assigned_ids = set(session.scalars(
            select(NinhBinhAssignment.staff_id).where(
                NinhBinhAssignment.year == ref.year, NinhBinhAssignment.month == ref.month
            )
        ).all())
        session.execute(update(Staff).values(ninh_binh_base=False))
        if assigned_ids:
            session.execute(update(Staff).where(Staff.bmo_id.in_(assigned_ids)).values(ninh_binh_base=True))
    get_staff_df.clear()
    get_all_staff.clear()


@st.cache_data(ttl=_CACHE_TTL_SECONDS)
def get_ninh_binh_assignment_months() -> frozenset[tuple[str, int, int]]:
    """Every (staff_id, year, month) ever marked as Ninh Binh base -- the
    full history, not just the current month. Weight calculations use this
    to resolve the exchange multiplier (see logic/weights.py) against the
    staff's Ninh Binh status *as of the assignment's own month*, instead of
    `Staff.ninh_binh_base` (which is only a snapshot of the current month
    and would otherwise silently rewrite past months' duty scores every
    time this month's Ninh Binh roster changes)."""
    with get_readonly_session() as session:
        rows = session.scalars(select(NinhBinhAssignment)).all()
        return frozenset((r.staff_id, r.year, r.month) for r in rows)


@st.cache_resource
def sync_ninh_binh_base_on_startup() -> None:
    """Runs `sync_ninh_binh_base` exactly once per server process instead of
    on every script rerun: `st.cache_resource`'s cache is shared across all
    sessions and reruns until the process restarts (or the cache is
    cleared), so this avoids an extra write query against the remote DB on
    every user interaction just to re-derive a value that only changes when
    the "Đi cơ sở Ninh Bình" sheet is saved (which calls the uncached
    `sync_ninh_binh_base` directly) or a calendar month boundary passes."""
    sync_ninh_binh_base()


# ---------------------------------------------------------------------------
# Duty weights
# ---------------------------------------------------------------------------

DUTY_WEIGHT_COLUMNS = ["duty_code", "duty_type", "description", "duty_weight", "multiplier"]


@st.cache_data(ttl=_CACHE_TTL_SECONDS)
def get_duty_weights_df() -> pd.DataFrame:
    with get_readonly_session() as session:
        rows = session.scalars(select(DutyWeight)).all()
        data = [{col: getattr(r, col) for col in DUTY_WEIGHT_COLUMNS} for r in rows]
    return pd.DataFrame(data, columns=DUTY_WEIGHT_COLUMNS)


def upsert_duty_weights_df(df: pd.DataFrame) -> None:
    with get_session() as session:
        existing_codes = {dw.duty_code for dw in session.scalars(select(DutyWeight)).all()}
        seen_codes: set[int] = set()

        for _, row in df.iterrows():
            duty_code = int(row["duty_code"])
            dw = session.get(DutyWeight, duty_code)
            if dw is None:
                dw = DutyWeight(duty_code=duty_code)
                session.add(dw)
            dw.duty_type = str(row["duty_type"]).strip()
            dw.description = row.get("description") or None
            dw.duty_weight = float(row["duty_weight"]) if pd.notna(row.get("duty_weight")) else None
            dw.multiplier = float(row["multiplier"]) if pd.notna(row.get("multiplier")) else None
            seen_codes.add(duty_code)

        for stale_code in existing_codes - seen_codes:
            stale = session.get(DutyWeight, stale_code)
            if stale is not None:
                session.delete(stale)
    get_duty_weights_df.clear()
    get_duty_weights.clear()


def import_duty_weights_df(df: pd.DataFrame) -> int:
    """Upsert rows from an uploaded spreadsheet by duty_code, additive
    (does not delete existing rows missing from the file)."""
    count = 0
    with get_session() as session:
        for _, row in df.iterrows():
            duty_code = int(row["duty_code"])
            dw = session.get(DutyWeight, duty_code)
            if dw is None:
                dw = DutyWeight(duty_code=duty_code)
                session.add(dw)
            dw.duty_type = str(row["duty_type"]).strip()
            dw.description = row.get("description") or None
            dw.duty_weight = float(row["duty_weight"]) if pd.notna(row.get("duty_weight")) else None
            dw.multiplier = float(row["multiplier"]) if pd.notna(row.get("multiplier")) else None
            count += 1
    get_duty_weights_df.clear()
    get_duty_weights.clear()
    return count


@st.cache_data(ttl=_CACHE_TTL_SECONDS)
def get_duty_weights() -> dict[int, DutyWeightRule]:
    with get_readonly_session() as session:
        rows = session.scalars(select(DutyWeight)).all()
        return {
            r.duty_code: DutyWeightRule(
                duty_code=r.duty_code, duty_type=r.duty_type, description=r.description,
                duty_weight=r.duty_weight, multiplier=r.multiplier,
            )
            for r in rows
        }


# ---------------------------------------------------------------------------
# Holidays
# ---------------------------------------------------------------------------

@st.cache_data(ttl=_CACHE_TTL_SECONDS)
def get_holidays_df(is_recurring: bool) -> pd.DataFrame:
    with get_readonly_session() as session:
        stmt = select(Holiday).where(Holiday.is_recurring.is_(is_recurring))
        rows = session.scalars(stmt).all()
        cols = ["id", "name", "month", "day"] if is_recurring else ["id", "name", "month", "day", "year"]
        data = [{col: getattr(r, col) for col in cols} for r in rows]
    return pd.DataFrame(data, columns=cols)


def _clear_holiday_caches() -> None:
    get_holidays_df.clear()
    get_all_holidays.clear()


def add_holiday(name: str, is_recurring: bool, month: int, day: int, year: int | None) -> None:
    with get_session() as session:
        session.add(Holiday(name=name, is_recurring=is_recurring, month=month, day=day, year=year))
    _clear_holiday_caches()


def delete_holiday(holiday_id: int) -> None:
    with get_session() as session:
        h = session.get(Holiday, holiday_id)
        if h is not None:
            session.delete(h)
    _clear_holiday_caches()


def sync_holidays_df(df: pd.DataFrame, is_recurring: bool) -> None:
    """Full sync for one holiday sub-table (recurring or manual)."""
    with get_session() as session:
        stmt = select(Holiday).where(Holiday.is_recurring.is_(is_recurring))
        existing_ids = {h.id for h in session.scalars(stmt).all()}
        seen_ids: set[int] = set()

        for _, row in df.iterrows():
            raw_id = row.get("id")
            holiday_id = int(raw_id) if pd.notna(raw_id) else None
            holiday = session.get(Holiday, holiday_id) if holiday_id else None
            if holiday is None:
                holiday = Holiday(is_recurring=is_recurring)
                session.add(holiday)
            holiday.name = str(row["name"]).strip()
            holiday.month = int(row["month"])
            holiday.day = int(row["day"])
            holiday.year = int(row["year"]) if (not is_recurring and pd.notna(row.get("year"))) else None
            session.flush()
            seen_ids.add(holiday.id)

        for stale_id in existing_ids - seen_ids:
            stale = session.get(Holiday, stale_id)
            if stale is not None:
                session.delete(stale)
    _clear_holiday_caches()


def import_holidays_df(df: pd.DataFrame) -> int:
    """Upsert rows from an uploaded spreadsheet (columns: name, is_recurring,
    month, day, year), additive. A row is matched to an existing holiday by
    (is_recurring, month, day, year) -- the same combination the DB's unique
    constraint enforces -- and its name is updated; otherwise a new holiday
    is inserted."""
    count = 0
    with get_session() as session:
        for _, row in df.iterrows():
            is_recurring = _to_bool(row.get("is_recurring"))
            month = int(row["month"])
            day = int(row["day"])
            year = None if is_recurring else int(row["year"])

            stmt = select(Holiday).where(
                Holiday.is_recurring.is_(is_recurring),
                Holiday.month == month,
                Holiday.day == day,
                Holiday.year == year,
            )
            holiday = session.scalars(stmt).first()
            if holiday is None:
                holiday = Holiday(is_recurring=is_recurring, month=month, day=day, year=year)
                session.add(holiday)
            holiday.name = str(row["name"]).strip()
            count += 1
    _clear_holiday_caches()
    return count


@st.cache_data(ttl=_CACHE_TTL_SECONDS)
def get_all_holidays() -> list[HolidayRule]:
    with get_readonly_session() as session:
        rows = session.scalars(select(Holiday)).all()
        return [
            HolidayRule(name=r.name, is_recurring=r.is_recurring, month=r.month, day=r.day, year=r.year)
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

class DuplicateAssignmentError(Exception):
    pass


def get_assignments_for_range(start: date, end: date) -> list[AssignmentRecord]:
    with get_readonly_session() as session:
        stmt = select(Assignment).where(Assignment.duty_date >= start, Assignment.duty_date <= end)
        rows = session.scalars(stmt).all()
        return [
            AssignmentRecord(duty_date=r.duty_date, base=r.base, staff_id=r.staff_id, is_half_day=r.is_half_day)
            for r in rows
        ]


def get_assignments_for_months(year: int, month: int, n_trailing: int) -> list[AssignmentRecord]:
    """Assignments covering the reference month and its trailing months
    (enough range for compute_monthly_weights)."""
    zero_based_start = (year * 12 + (month - 1)) - n_trailing
    start_year, start_month = zero_based_start // 12, zero_based_start % 12 + 1
    start = date(start_year, start_month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = date(year, month, last_day)
    return get_assignments_for_range(start, end)


def get_assignments_for_year_months(year_months: list[tuple[int, int]]) -> list[AssignmentRecord]:
    """Assignments covering a (possibly non-contiguous) set of (year, month)
    pairs, fetched as a single range query spanning the earliest to the
    latest selected month."""
    if not year_months:
        return []
    start_year, start_month = min(year_months)
    end_year, end_month = max(year_months)
    start = date(start_year, start_month, 1)
    end = date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])
    return get_assignments_for_range(start, end)


def assign_staff(duty_date: date, base: str, staff_id: str, is_half_day: bool = False) -> None:
    with get_session() as session:
        session.add(Assignment(duty_date=duty_date, base=base, staff_id=staff_id, is_half_day=is_half_day))
        try:
            session.flush()
        except IntegrityError as exc:
            raise DuplicateAssignmentError(
                f"{staff_id} is already assigned to {base} on {duty_date}."
            ) from exc


def unassign_staff(assignment_id: int) -> None:
    with get_session() as session:
        a = session.get(Assignment, assignment_id)
        if a is not None:
            session.delete(a)


def set_half_day(assignment_id: int, is_half_day: bool) -> None:
    with get_session() as session:
        a = session.get(Assignment, assignment_id)
        if a is not None:
            a.is_half_day = is_half_day


def find_assignment(duty_date: date, base: str, staff_id: str) -> dict | None:
    """The assignment (if any) for this staff on this date at this base --
    used to detect a same-day cross-base conflict before creating a new one
    at the other base."""
    with get_readonly_session() as session:
        stmt = select(Assignment).where(
            Assignment.duty_date == duty_date, Assignment.base == base, Assignment.staff_id == staff_id
        )
        a = session.scalars(stmt).first()
        if a is None:
            return None
        return {
            "id": a.id, "duty_date": a.duty_date, "base": a.base, "staff_id": a.staff_id,
            "is_half_day": a.is_half_day,
        }


def move_assignment(assignment_id: int, new_base: str, is_half_day: bool | None = None) -> None:
    """Re-assign an existing assignment to a different base (same date,
    same staff) -- used when the user confirms moving a staff member from
    one base to the other on the same day instead of double-booking them.
    `is_half_day` overrides the half-day flag too when given (the calendar
    dialog's current half-day checkbox should apply uniformly whether a
    staff member is freshly assigned or moved into the target base)."""
    with get_session() as session:
        a = session.get(Assignment, assignment_id)
        if a is not None:
            staff_id, duty_date = a.staff_id, a.duty_date  # read before flush; may raise
            a.base = new_base
            if is_half_day is not None:
                a.is_half_day = is_half_day
            try:
                session.flush()
            except IntegrityError as exc:
                raise DuplicateAssignmentError(
                    f"{staff_id} is already assigned to {new_base} on {duty_date}."
                ) from exc


def delete_all_assignments() -> int:
    """Wipe every duty-schedule assignment (all months), used by the
    calendar page's "Xóa tất cả lịch trực" reset action. Irreversible."""
    with get_session() as session:
        result = session.execute(delete(Assignment))
        return result.rowcount


def get_assignments_with_ids_for_range(start: date, end: date) -> list[dict]:
    """Like get_assignments_for_range but keeps the row id, needed by the
    calendar UI to build per-event "unassign" actions."""
    with get_readonly_session() as session:
        stmt = select(Assignment).where(Assignment.duty_date >= start, Assignment.duty_date <= end)
        rows = session.scalars(stmt).all()
        return [
            {
                "id": r.id, "duty_date": r.duty_date, "base": r.base, "staff_id": r.staff_id,
                "is_half_day": r.is_half_day,
            }
            for r in rows
        ]
