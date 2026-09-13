"""Plain dataclasses used by the framework-agnostic logic layer.

No Streamlit or SQLAlchemy imports here: these are the shapes the UI and
repository layers convert into/out of, so the logic module stays trivially
unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class StaffInfo:
    bmo_id: str
    ho_va_ten: str
    gioi_tinh: str | None
    trinh_do: str | None
    vi_tri: str
    so_dien_thoai: str | None
    mang_thai: bool
    sinh_de: bool
    ghi_chu: str | None
    ninh_binh_base: bool
    is_active: bool = True


@dataclass(frozen=True)
class DutyWeightRule:
    duty_code: int
    duty_type: str
    description: str | None
    duty_weight: float | None
    multiplier: float | None


@dataclass(frozen=True)
class HolidayRule:
    name: str
    is_recurring: bool
    month: int
    day: int
    year: int | None = None


@dataclass(frozen=True)
class AssignmentRecord:
    duty_date: date
    base: str
    staff_id: str
    is_half_day: bool = False
