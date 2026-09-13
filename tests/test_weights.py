from datetime import date

from app.config import BASE_HANOI, BASE_NINH_BINH
from app.logic.types import AssignmentRecord, DutyWeightRule, StaffInfo
from app.logic.weights import (
    compute_monthly_weights,
    compute_peer_average,
    compute_single_month_weight,
    resolve_assignment_weight,
)

DUTY_WEIGHTS = {
    1: DutyWeightRule(1, "normal_day", "Mon-Thu", 1.0, None),
    2: DutyWeightRule(2, "friday", "Friday", 1.5, None),
    3: DutyWeightRule(3, "saturday", "Saturday", 2.5, None),
    4: DutyWeightRule(4, "sunday", "Sunday", 2.0, None),
    5: DutyWeightRule(5, "holidays", "Holiday", 3.0, None),
    9: DutyWeightRule(9, "exchange_base", "Ha Noi -> Ninh Binh", None, 1.25),
    10: DutyWeightRule(10, "weekend_half", "Half-day Sat/Sun", None, 0.5),
}


def _staff(bmo_id: str, ninh_binh_base: bool) -> StaffInfo:
    return StaffInfo(
        bmo_id=bmo_id,
        ho_va_ten="Vương Hoàng Hùng",
        gioi_tinh="Nam",
        trinh_do="Đại học",
        vi_tri="Dược lâm sàng",
        so_dien_thoai="0123456789",
        mang_thai=False,
        sinh_de=False,
        ghi_chu=None,
        ninh_binh_base=ninh_binh_base,
    )


def test_notes_md_worked_example_hanoi_home_exchanged_to_ninh_binh():
    """Reproduces the notes.md scenario: a Ha-Noi-home staff works 2 normal
    days at Ha Noi (1 weight each) plus 1 Sunday delegated to Ninh Binh
    (2 * 1.25 = 2.5 weight) => 1 + 1 + 2.5 = 4.5 total.

    Note: notes.md's own prose states the total as "5.5", but its own
    breakdown (2 + 2.5) sums to 4.5 -- that specific figure is an
    arithmetic typo in the source document. This test follows the
    documented formula/breakdown, which is unambiguous, rather than the
    inconsistent headline number.
    """
    staff = _staff("0013", ninh_binh_base=False)
    assignments = [
        AssignmentRecord(date(2026, 9, 7), BASE_HANOI, staff.bmo_id),  # Monday
        AssignmentRecord(date(2026, 9, 8), BASE_HANOI, staff.bmo_id),  # Tuesday
        AssignmentRecord(date(2026, 9, 13), BASE_NINH_BINH, staff.bmo_id),  # Sunday
    ]
    total = sum(resolve_assignment_weight(a, staff, [], DUTY_WEIGHTS) for a in assignments)
    assert total == 4.5


def test_same_schedule_when_staff_is_ninh_binh_home_no_multiplier():
    """Per notes.md: if the staff is Ninh-Binh-based throughout (no base
    exchange), the same 2 normal days + 1 Sunday totals 2 + 2 = 4 -- no
    multiplier applies since he is working at his home base."""
    staff = _staff("0013", ninh_binh_base=True)
    assignments = [
        AssignmentRecord(date(2026, 9, 7), BASE_NINH_BINH, staff.bmo_id),
        AssignmentRecord(date(2026, 9, 8), BASE_NINH_BINH, staff.bmo_id),
        AssignmentRecord(date(2026, 9, 13), BASE_NINH_BINH, staff.bmo_id),
    ]
    total = sum(resolve_assignment_weight(a, staff, [], DUTY_WEIGHTS) for a in assignments)
    assert total == 4.0


def test_multiplier_is_one_way_only_ninh_binh_home_at_hanoi_gets_no_multiplier():
    """Confirmed decision: the 1.25 exchange multiplier is one-way (Ha Noi
    home -> Ninh Binh base only). A Ninh-Binh-home staff working at Ha Noi
    should NOT be multiplied."""
    staff = _staff("0013", ninh_binh_base=True)
    assignment = AssignmentRecord(date(2026, 9, 13), BASE_HANOI, staff.bmo_id)  # Sunday
    assert resolve_assignment_weight(assignment, staff, [], DUTY_WEIGHTS) == 2.0


def test_weekend_half_saturday():
    staff = _staff("0013", ninh_binh_base=False)
    assignment = AssignmentRecord(date(2026, 9, 12), BASE_HANOI, staff.bmo_id, is_half_day=True)  # Saturday
    assert resolve_assignment_weight(assignment, staff, [], DUTY_WEIGHTS) == 1.25  # 2.5 * 0.5


def test_weekend_half_sunday():
    staff = _staff("0013", ninh_binh_base=False)
    assignment = AssignmentRecord(date(2026, 9, 13), BASE_HANOI, staff.bmo_id, is_half_day=True)  # Sunday
    assert resolve_assignment_weight(assignment, staff, [], DUTY_WEIGHTS) == 1.0  # 2.0 * 0.5


def test_weekend_half_stacks_with_exchange_multiplier():
    """Hanoi-home staff, half-day Sunday delegated to Ninh Binh:
    2.0 (sunday) * 0.5 (half-day) * 1.25 (exchange) = 1.25."""
    staff = _staff("0013", ninh_binh_base=False)
    assignment = AssignmentRecord(date(2026, 9, 13), BASE_NINH_BINH, staff.bmo_id, is_half_day=True)
    assert resolve_assignment_weight(assignment, staff, [], DUTY_WEIGHTS) == 1.25


def test_weekend_half_flag_ignored_on_a_weekday():
    """is_half_day only means something on a Sat/Sun; on a normal weekday
    it has no effect on the resolved weight."""
    staff = _staff("0013", ninh_binh_base=False)
    assignment = AssignmentRecord(date(2026, 9, 7), BASE_HANOI, staff.bmo_id, is_half_day=True)  # Monday
    assert resolve_assignment_weight(assignment, staff, [], DUTY_WEIGHTS) == 1.0


def test_weekend_half_flag_ignored_when_day_is_a_holiday():
    """A Saturday that's also a holiday resolves as a holiday (duty_code 5),
    so the half-day flag (scoped to duty_code 3/4) has no effect."""
    from app.logic.types import HolidayRule

    staff = _staff("0013", ninh_binh_base=False)
    holidays = [HolidayRule(name="Nghi le", is_recurring=False, month=9, day=12, year=2026)]
    assignment = AssignmentRecord(date(2026, 9, 12), BASE_HANOI, staff.bmo_id, is_half_day=True)  # Saturday
    assert resolve_assignment_weight(assignment, staff, holidays, DUTY_WEIGHTS) == 3.0  # full holiday weight


def test_compute_single_month_weight():
    staff = _staff("0013", ninh_binh_base=False)
    staff_by_id = {staff.bmo_id: staff}
    assignments = [
        AssignmentRecord(date(2026, 9, 7), BASE_HANOI, staff.bmo_id),  # Monday, 1.0
        AssignmentRecord(date(2026, 10, 5), BASE_HANOI, staff.bmo_id),  # different month
    ]
    total = compute_single_month_weight(staff.bmo_id, 2026, 9, assignments, staff_by_id, [], DUTY_WEIGHTS)
    assert total == 1.0


def test_compute_monthly_weights_includes_trailing_months():
    staff = _staff("0013", ninh_binh_base=False)
    staff_by_id = {staff.bmo_id: staff}
    assignments = [
        AssignmentRecord(date(2026, 7, 6), BASE_HANOI, staff.bmo_id),  # Monday, July
        AssignmentRecord(date(2026, 8, 3), BASE_HANOI, staff.bmo_id),  # Monday, August
        AssignmentRecord(date(2026, 9, 7), BASE_HANOI, staff.bmo_id),  # Monday, September
    ]
    result = compute_monthly_weights(
        staff.bmo_id, 2026, 9, assignments, staff_by_id, [], DUTY_WEIGHTS, n_trailing=2
    )
    assert result == {"2026-07": 1.0, "2026-08": 1.0, "2026-09": 1.0}


def test_compute_monthly_weights_year_rollover():
    staff = _staff("0013", ninh_binh_base=False)
    staff_by_id = {staff.bmo_id: staff}
    assignments = [
        AssignmentRecord(date(2025, 12, 1), BASE_HANOI, staff.bmo_id),  # Monday, Dec 2025
    ]
    result = compute_monthly_weights(
        staff.bmo_id, 2026, 1, assignments, staff_by_id, [], DUTY_WEIGHTS, n_trailing=2
    )
    assert result == {"2025-11": 0.0, "2025-12": 1.0, "2026-01": 0.0}


def test_compute_peer_average_by_trinh_do():
    dai_hoc_a = _staff("0013", ninh_binh_base=False)
    dai_hoc_b = StaffInfo(
        bmo_id="0014", ho_va_ten="Lê Hoàng Trung", gioi_tinh="Nam", trinh_do="Đại học",
        vi_tri="Dược lâm sàng", so_dien_thoai="0123456789", mang_thai=False, sinh_de=False,
        ghi_chu=None, ninh_binh_base=False,
    )
    cao_dang = StaffInfo(
        bmo_id="0001", ho_va_ten="Đỗ Thanh Hương", gioi_tinh="Nữ", trinh_do="Cao đẳng",
        vi_tri="Hồ sơ", so_dien_thoai="0123456789", mang_thai=True, sinh_de=False,
        ghi_chu=None, ninh_binh_base=False,
    )
    all_staff = [dai_hoc_a, dai_hoc_b, cao_dang]
    assignments = [
        AssignmentRecord(date(2026, 9, 7), BASE_HANOI, "0013"),  # 1.0
        AssignmentRecord(date(2026, 9, 11), BASE_HANOI, "0014"),  # Friday, 1.5
        AssignmentRecord(date(2026, 9, 7), BASE_HANOI, "0001"),  # 1.0 (Cao dang, excluded)
    ]
    avg = compute_peer_average("Đại học", 2026, 9, all_staff, assignments, [], DUTY_WEIGHTS)
    assert avg == (1.0 + 1.5) / 2
