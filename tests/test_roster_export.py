from datetime import date

from app.config import BASE_HANOI, BASE_NINH_BINH
from app.logic.roster_export import build_roster_rows
from app.logic.types import AssignmentRecord, StaffInfo


def _staff(bmo_id: str, ho_va_ten: str, trinh_do: str | None) -> StaffInfo:
    return StaffInfo(
        bmo_id=bmo_id,
        ho_va_ten=ho_va_ten,
        gioi_tinh="Nam",
        trinh_do=trinh_do,
        vi_tri="Dược lâm sàng",
        so_dien_thoai=None,
        mang_thai=False,
        sinh_de=False,
        ghi_chu=None,
        ninh_binh_base=False,
    )


def test_one_row_per_day_of_month_september_has_30_rows():
    rows = build_roster_rows([], {}, BASE_HANOI, 2026, 9)
    assert len(rows) == 30
    assert rows[0].day == date(2026, 9, 1)
    assert rows[-1].day == date(2026, 9, 30)


def test_weekday_label_matches_config_table():
    # 2026-09-07 is a Monday.
    rows = build_roster_rows([], {}, BASE_HANOI, 2026, 9)
    assert rows[6].day == date(2026, 9, 7)
    assert rows[6].weekday_label == "T2"


def test_single_staff_lands_in_dai_hoc_24_column():
    staff = _staff("0001", "Vương Hoàng Hùng", "Đại học")
    assignments = [AssignmentRecord(date(2026, 9, 1), BASE_HANOI, staff.bmo_id)]
    rows = build_roster_rows(assignments, {staff.bmo_id: staff}, BASE_HANOI, 2026, 9)
    assert rows[0].dai_hoc_24 == "Vương Hoàng Hùng"
    assert rows[0].dai_hoc_12 == ""
    assert rows[0].cao_dang_24 == ""


def test_half_day_flag_routes_to_the_12_24_column():
    staff = _staff("0001", "Lê Hoàng Trung", "Cao đẳng")
    assignments = [AssignmentRecord(date(2026, 9, 1), BASE_HANOI, staff.bmo_id, is_half_day=True)]
    rows = build_roster_rows(assignments, {staff.bmo_id: staff}, BASE_HANOI, 2026, 9)
    assert rows[0].cao_dang_12 == "Lê Hoàng Trung"
    assert rows[0].cao_dang_24 == ""


def test_multiple_staff_in_one_cell_are_joined_with_semicolon():
    a = _staff("0001", "Nguyễn Thị Bích Ngọc", "Đại học")
    b = _staff("0002", "Đặng Minh Đức", "Đại học")
    assignments = [
        AssignmentRecord(date(2026, 9, 1), BASE_HANOI, a.bmo_id),
        AssignmentRecord(date(2026, 9, 1), BASE_HANOI, b.bmo_id),
    ]
    rows = build_roster_rows(assignments, {a.bmo_id: a, b.bmo_id: b}, BASE_HANOI, 2026, 9)
    assert rows[0].dai_hoc_24 == "Nguyễn Thị Bích Ngọc;\nĐặng Minh Đức"


def test_other_base_is_excluded():
    staff = _staff("0001", "Vương Hoàng Hùng", "Đại học")
    assignments = [AssignmentRecord(date(2026, 9, 1), BASE_NINH_BINH, staff.bmo_id)]
    rows = build_roster_rows(assignments, {staff.bmo_id: staff}, BASE_HANOI, 2026, 9)
    assert rows[0].dai_hoc_24 == ""


def test_days_with_no_assignment_stay_blank():
    rows = build_roster_rows([], {}, BASE_HANOI, 2026, 9)
    assert all(r.dai_hoc_24 == r.dai_hoc_12 == r.cao_dang_24 == r.cao_dang_12 == "" for r in rows)


def test_unknown_staff_id_is_skipped_not_crashed():
    assignments = [AssignmentRecord(date(2026, 9, 1), BASE_HANOI, "does-not-exist")]
    rows = build_roster_rows(assignments, {}, BASE_HANOI, 2026, 9)
    assert rows[0].dai_hoc_24 == rows[0].cao_dang_24 == ""


def test_staff_with_unrecognized_trinh_do_is_skipped():
    staff = _staff("0001", "Vương Hoàng Hùng", trinh_do=None)
    assignments = [AssignmentRecord(date(2026, 9, 1), BASE_HANOI, staff.bmo_id)]
    rows = build_roster_rows(assignments, {staff.bmo_id: staff}, BASE_HANOI, 2026, 9)
    assert rows[0].dai_hoc_24 == rows[0].cao_dang_24 == ""
