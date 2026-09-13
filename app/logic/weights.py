"""Duty-weight calculation: per-assignment weight, monthly accumulation,
and peer averages, used to keep duty schedules balanced across staff.
"""

from __future__ import annotations

from app.config import BASE_NINH_BINH, EXCHANGE_MULTIPLIER_DUTY_CODE, N_TRAILING_MONTHS, WEEKEND_HALF_DUTY_CODE
from app.logic.calendar_rules import DUTY_CODE_SATURDAY, DUTY_CODE_SUNDAY, resolve_day_type
from app.logic.types import AssignmentRecord, DutyWeightRule, HolidayRule, StaffInfo


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    zero_based = (year * 12 + (month - 1)) + delta
    return zero_based // 12, zero_based % 12 + 1


def resolve_assignment_weight(
    assignment: AssignmentRecord,
    staff: StaffInfo,
    holidays: list[HolidayRule],
    duty_weights: dict[int, DutyWeightRule],
) -> float:
    """Weight of a single assignment: the day-type weight -- halved when
    the assignment is flagged as a half-day Saturday/Sunday shift -- times
    the one-way Ha-Noi-home -> Ninh-Binh-base exchange multiplier when it
    applies (confirmed one-directional; a Ninh-Binh-home staff working at
    Ha Noi gets no multiplier). Both adjustments stack."""
    duty_code = resolve_day_type(assignment.duty_date, holidays)
    base_weight = duty_weights[duty_code].duty_weight or 0.0

    if assignment.is_half_day and duty_code in (DUTY_CODE_SATURDAY, DUTY_CODE_SUNDAY):
        half_multiplier = duty_weights[WEEKEND_HALF_DUTY_CODE].multiplier or 0.5
        base_weight *= half_multiplier

    is_exchange = assignment.base == BASE_NINH_BINH and not staff.ninh_binh_base
    if is_exchange:
        multiplier = duty_weights[EXCHANGE_MULTIPLIER_DUTY_CODE].multiplier or 1.0
        return base_weight * multiplier
    return base_weight


def compute_single_month_weight(
    staff_id: str,
    year: int,
    month: int,
    assignments: list[AssignmentRecord],
    staff_by_id: dict[str, StaffInfo],
    holidays: list[HolidayRule],
    duty_weights: dict[int, DutyWeightRule],
) -> float:
    """Total duty-weight for one staff member in a single given month."""
    staff = staff_by_id[staff_id]
    total = 0.0
    for a in assignments:
        if a.staff_id != staff_id:
            continue
        if a.duty_date.year != year or a.duty_date.month != month:
            continue
        total += resolve_assignment_weight(a, staff, holidays, duty_weights)
    return total


def compute_monthly_weights(
    staff_id: str,
    ref_year: int,
    ref_month: int,
    assignments: list[AssignmentRecord],
    staff_by_id: dict[str, StaffInfo],
    holidays: list[HolidayRule],
    duty_weights: dict[int, DutyWeightRule],
    n_trailing: int = N_TRAILING_MONTHS,
) -> dict[str, float]:
    """Per-month duty-weight totals for the reference month and each of the
    `n_trailing` months immediately before it, keyed "YYYY-MM"."""
    result: dict[str, float] = {}
    for delta in range(-n_trailing, 1):
        year, month = _shift_month(ref_year, ref_month, delta)
        key = f"{year:04d}-{month:02d}"
        result[key] = compute_single_month_weight(
            staff_id, year, month, assignments, staff_by_id, holidays, duty_weights
        )
    return result


def compute_peer_average(
    trinh_do: str,
    ref_year: int,
    ref_month: int,
    all_staff: list[StaffInfo],
    assignments: list[AssignmentRecord],
    holidays: list[HolidayRule],
    duty_weights: dict[int, DutyWeightRule],
) -> float:
    """Average total weight for the reference month across active staff
    sharing the given trinh_do (certificate level)."""
    peers = [s for s in all_staff if s.is_active and s.trinh_do == trinh_do]
    if not peers:
        return 0.0

    staff_by_id = {s.bmo_id: s for s in peers}
    totals = [
        compute_single_month_weight(s.bmo_id, ref_year, ref_month, assignments, staff_by_id, holidays, duty_weights)
        for s in peers
    ]
    return sum(totals) / len(totals)
