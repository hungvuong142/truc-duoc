from datetime import date

from app.logic.calendar_rules import (
    DUTY_CODE_FRIDAY,
    DUTY_CODE_HOLIDAY,
    DUTY_CODE_NORMAL_DAY,
    DUTY_CODE_SATURDAY,
    DUTY_CODE_SUNDAY,
    classify_position,
    is_holiday,
    resolve_day_type,
)
from app.logic.types import HolidayRule


def test_classify_position_nha_thuoc():
    assert classify_position("Nhà thuốc K1") == "Nhà thuốc"


def test_classify_position_noi_tru():
    assert classify_position("Hồ sơ") == "Nội trú"
    assert classify_position("Dược lâm sàng") == "Nội trú"


def test_resolve_day_type_weekdays_mon_to_thu():
    for day in (2026, 9, 7), (2026, 9, 8), (2026, 9, 9), (2026, 9, 10):
        year, month, dom = day
        assert resolve_day_type(date(year, month, dom), []) == DUTY_CODE_NORMAL_DAY


def test_resolve_day_type_friday_saturday_sunday():
    assert resolve_day_type(date(2026, 9, 11), []) == DUTY_CODE_FRIDAY
    assert resolve_day_type(date(2026, 9, 12), []) == DUTY_CODE_SATURDAY
    assert resolve_day_type(date(2026, 9, 13), []) == DUTY_CODE_SUNDAY


def test_recurring_holiday_applies_every_year():
    holidays = [HolidayRule(name="Quoc Khanh", is_recurring=True, month=9, day=2)]
    assert is_holiday(date(2026, 9, 2), holidays)
    assert is_holiday(date(2030, 9, 2), holidays)


def test_manual_holiday_only_applies_to_its_year():
    holidays = [HolidayRule(name="Nghi bu", is_recurring=False, month=9, day=3, year=2026)]
    assert is_holiday(date(2026, 9, 3), holidays)
    assert not is_holiday(date(2027, 9, 3), holidays)


def test_holiday_overrides_weekday_classification():
    # A Tuesday (would normally be duty_code 1) that is also a manual holiday.
    holidays = [HolidayRule(name="Nghi le", is_recurring=False, month=9, day=1, year=2026)]
    d = date(2026, 9, 1)
    assert d.weekday() == 1  # sanity check: it's a Tuesday
    assert resolve_day_type(d, holidays) == DUTY_CODE_HOLIDAY
