"""Calendar/holiday resolution rules (day type -> duty_code)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from app.config import NHA_THUOC_KEYWORD
from app.logic.types import HolidayRule

DUTY_CODE_NORMAL_DAY = 1
DUTY_CODE_FRIDAY = 2
DUTY_CODE_SATURDAY = 3
DUTY_CODE_SUNDAY = 4
DUTY_CODE_HOLIDAY = 5


def classify_position(vi_tri: str) -> Literal["Nhà thuốc", "Nội trú"]:
    """Any vi_tri not containing "Nhà thuốc" is grouped as "Nội trú"."""
    return "Nhà thuốc" if NHA_THUOC_KEYWORD in vi_tri else "Nội trú"


def find_holiday(d: date, holidays: list[HolidayRule]) -> HolidayRule | None:
    for h in holidays:
        if h.month != d.month or h.day != d.day:
            continue
        if h.is_recurring or h.year == d.year:
            return h
    return None


def is_holiday(d: date, holidays: list[HolidayRule]) -> bool:
    return find_holiday(d, holidays) is not None


def resolve_holiday_name(d: date, holidays: list[HolidayRule]) -> str | None:
    holiday = find_holiday(d, holidays)
    return holiday.name if holiday else None


def resolve_day_type(d: date, holidays: list[HolidayRule]) -> int:
    """Return the duty_code (1-5) for a given date.

    Holiday status overrides the weekday-based classification.
    """
    if is_holiday(d, holidays):
        return DUTY_CODE_HOLIDAY

    weekday = d.weekday()  # Monday=0 ... Sunday=6
    if weekday <= 3:  # Mon-Thu
        return DUTY_CODE_NORMAL_DAY
    if weekday == 4:  # Friday
        return DUTY_CODE_FRIDAY
    if weekday == 5:  # Saturday
        return DUTY_CODE_SATURDAY
    return DUTY_CODE_SUNDAY  # Sunday
