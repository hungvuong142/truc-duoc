from datetime import date

import pandas as pd
import pytest

from app import repository
from app.config import BASE_HANOI, BASE_NINH_BINH


def _sample_staff_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "bmo_id": "0001", "ho_va_ten": "Nguyễn Văn A", "tuoi": 30,
            "gioi_tinh": "Nam", "trinh_do": "Cao đẳng", "vi_tri": "Hồ sơ",
            "so_dien_thoai": "0123456789", "mang_thai": False, "sinh_de": False,
            "ghi_chu": None, "ninh_binh_base": False, "is_active": True,
        },
        {
            "bmo_id": "0002", "ho_va_ten": "Trần Thị B", "tuoi": 28,
            "gioi_tinh": "Nữ", "trinh_do": "Đại học", "vi_tri": "Dược lâm sàng",
            "so_dien_thoai": "0987654321", "mang_thai": True, "sinh_de": False,
            "ghi_chu": None, "ninh_binh_base": True, "is_active": True,
        },
    ])


def test_upsert_and_get_staff_df(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    df = repository.get_staff_df()
    assert len(df) == 2
    assert df["mang_thai"].dtype == bool
    row_b = df[df["bmo_id"] == "0002"].iloc[0]
    assert bool(row_b["mang_thai"]) is True
    assert bool(row_b["ninh_binh_base"]) is True


def test_upsert_staff_df_deletes_missing_rows(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    only_one = _sample_staff_df().iloc[[0]]
    repository.upsert_staff_df(only_one)
    df = repository.get_staff_df()
    assert list(df["bmo_id"]) == ["0001"]


def test_new_staff_row_gets_generated_id(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    df = repository.get_staff_df()
    new_row = pd.DataFrame([{
        "bmo_id": None, "ho_va_ten": "Lê Văn C", "tuoi": 25, "gioi_tinh": "Nam",
        "trinh_do": "Cao đẳng", "vi_tri": "Nhà thuốc K1", "so_dien_thoai": "0111222333",
        "mang_thai": False, "sinh_de": False, "ghi_chu": None, "ninh_binh_base": False,
        "is_active": True,
    }])
    repository.upsert_staff_df(pd.concat([df, new_row], ignore_index=True))
    df2 = repository.get_staff_df()
    assert len(df2) == 3
    assert "0003" in set(df2["bmo_id"])


def test_duty_weights_roundtrip(temp_db):
    df = pd.DataFrame([
        {"duty_code": 1, "duty_type": "normal_day", "description": "d", "duty_weight": 1.0, "multiplier": None},
        {"duty_code": 9, "duty_type": "exchange_base", "description": "e", "duty_weight": None, "multiplier": 1.25},
    ])
    repository.upsert_duty_weights_df(df)
    weights = repository.get_duty_weights()
    assert weights[1].duty_weight == 1.0
    assert weights[9].multiplier == 1.25
    assert weights[9].duty_weight is None


def test_holidays_add_and_sync(temp_db):
    repository.add_holiday("Quoc Khanh", is_recurring=True, month=9, day=2, year=None)
    repository.add_holiday("Nghi bu", is_recurring=False, month=9, day=3, year=2026)

    recurring = repository.get_all_holidays()
    assert len(recurring) == 2
    assert any(h.is_recurring and h.month == 9 and h.day == 2 for h in recurring)
    assert any(not h.is_recurring and h.year == 2026 for h in recurring)


def test_assign_staff_and_duplicate_rejected(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    d = date(2026, 9, 7)
    repository.assign_staff(d, BASE_HANOI, "0001")

    assignments = repository.get_assignments_for_range(d, d)
    assert len(assignments) == 1
    assert assignments[0].staff_id == "0001"
    assert assignments[0].base == BASE_HANOI

    with pytest.raises(repository.DuplicateAssignmentError):
        repository.assign_staff(d, BASE_HANOI, "0001")


def test_assign_staff_same_day_different_base_allowed(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    d = date(2026, 9, 7)
    repository.assign_staff(d, BASE_HANOI, "0001")
    repository.assign_staff(d, BASE_NINH_BINH, "0002")
    assert len(repository.get_assignments_for_range(d, d)) == 2


def test_unassign_staff(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    d = date(2026, 9, 7)
    repository.assign_staff(d, BASE_HANOI, "0001")
    [row] = repository.get_assignments_with_ids_for_range(d, d)
    repository.unassign_staff(row["id"])
    assert repository.get_assignments_for_range(d, d) == []


def test_get_assignments_for_months_covers_trailing_range(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    repository.assign_staff(date(2026, 7, 6), BASE_HANOI, "0001")
    repository.assign_staff(date(2026, 9, 30), BASE_HANOI, "0001")
    repository.assign_staff(date(2026, 6, 30), BASE_HANOI, "0001")  # outside trailing-2 window

    assignments = repository.get_assignments_for_months(2026, 9, n_trailing=2)
    dates = {a.duty_date for a in assignments}
    assert date(2026, 7, 6) in dates
    assert date(2026, 9, 30) in dates
    assert date(2026, 6, 30) not in dates


def test_get_assignments_for_year_months(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    repository.assign_staff(date(2026, 3, 1), BASE_HANOI, "0001")
    repository.assign_staff(date(2026, 9, 1), BASE_HANOI, "0001")
    repository.assign_staff(date(2026, 6, 1), BASE_HANOI, "0001")  # not selected

    assignments = repository.get_assignments_for_year_months([(2026, 3), (2026, 9)])
    dates = {a.duty_date for a in assignments}
    assert date(2026, 3, 1) in dates
    assert date(2026, 9, 1) in dates
    # the range query spans 3..9, so June is incidentally included in the
    # raw fetch -- callers filter to the exact selected months themselves.
    assert date(2026, 6, 1) in dates


def test_import_staff_df_does_not_delete_existing_rows(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    only_one = _sample_staff_df().iloc[[0]]
    repository.import_staff_df(only_one)
    df = repository.get_staff_df()
    assert set(df["bmo_id"]) == {"0001", "0002"}


def test_import_staff_df_string_bools(temp_db):
    df = pd.DataFrame([{
        "bmo_id": "0001", "ho_va_ten": "Nguyễn Văn A", "tuoi": 30,
        "gioi_tinh": "Nam", "trinh_do": "Cao đẳng", "vi_tri": "Hồ sơ",
        "so_dien_thoai": "0123456789", "mang_thai": "TRUE", "sinh_de": "0",
        "ghi_chu": None, "ninh_binh_base": "Có", "is_active": "1",
    }])
    repository.import_staff_df(df)
    row = repository.get_staff_df().iloc[0]
    assert bool(row["mang_thai"]) is True
    assert bool(row["sinh_de"]) is False
    assert bool(row["ninh_binh_base"]) is True
    assert bool(row["is_active"]) is True


def test_import_staff_df_normalizes_excel_stripped_bmo_id_and_phone(temp_db):
    """Simulates re-uploading an edited template: Excel turns "0001" into
    the bare int 1 and a phone number into a float once round-tripped."""
    repository.upsert_staff_df(_sample_staff_df())
    df = pd.DataFrame([{
        "bmo_id": 1, "ho_va_ten": "Nguyễn Văn A (updated)", "tuoi": 31,
        "gioi_tinh": "Nam", "trinh_do": "Cao đẳng", "vi_tri": "Hồ sơ",
        "so_dien_thoai": 123456789.0, "mang_thai": False, "sinh_de": False,
        "ghi_chu": None, "ninh_binh_base": False, "is_active": True,
    }])
    repository.import_staff_df(df)
    result = repository.get_staff_df()
    assert set(result["bmo_id"]) == {"0001", "0002"}  # updated in place, not duplicated
    row = result[result["bmo_id"] == "0001"].iloc[0]
    assert row["ho_va_ten"] == "Nguyễn Văn A (updated)"
    assert row["so_dien_thoai"] == "0123456789"


def test_import_duty_weights_df_does_not_delete_existing_rows(temp_db):
    repository.upsert_duty_weights_df(pd.DataFrame([
        {"duty_code": 1, "duty_type": "normal_day", "description": "d", "duty_weight": 1.0, "multiplier": None},
    ]))
    repository.import_duty_weights_df(pd.DataFrame([
        {"duty_code": 9, "duty_type": "exchange_base", "description": "e", "duty_weight": None, "multiplier": 1.25},
    ]))
    weights = repository.get_duty_weights()
    assert set(weights.keys()) == {1, 9}


def test_import_duty_weights_df_overrides_same_duty_code(temp_db):
    """Re-uploading a row with a duty_code that already exists updates it
    in place instead of erroring or creating a second row."""
    repository.upsert_duty_weights_df(pd.DataFrame([
        {"duty_code": 1, "duty_type": "normal_day", "description": "old", "duty_weight": 1.0, "multiplier": None},
    ]))
    repository.import_duty_weights_df(pd.DataFrame([
        {"duty_code": 1, "duty_type": "normal_day", "description": "new", "duty_weight": 2.0, "multiplier": None},
    ]))
    weights = repository.get_duty_weights()
    assert set(weights.keys()) == {1}
    assert weights[1].description == "new"
    assert weights[1].duty_weight == 2.0


def test_import_holidays_df_upserts_by_natural_key(temp_db):
    repository.add_holiday("Quoc Khanh cu", is_recurring=True, month=9, day=2, year=None)
    df = pd.DataFrame([
        {"name": "Quoc Khanh", "is_recurring": True, "month": 9, "day": 2, "year": None},
        {"name": "Nghi bu", "is_recurring": False, "month": 9, "day": 3, "year": 2026},
    ])
    repository.import_holidays_df(df)
    holidays = repository.get_all_holidays()
    assert len(holidays) == 2  # updated in place, not duplicated
    names = {h.name for h in holidays}
    assert names == {"Quoc Khanh", "Nghi bu"}


def test_find_assignment(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    d = date(2026, 9, 7)
    repository.assign_staff(d, BASE_HANOI, "0001")

    found = repository.find_assignment(d, BASE_HANOI, "0001")
    assert found is not None
    assert found["base"] == BASE_HANOI

    assert repository.find_assignment(d, BASE_NINH_BINH, "0001") is None


def test_move_assignment_changes_base(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    d = date(2026, 9, 7)
    repository.assign_staff(d, BASE_HANOI, "0001")
    [row] = repository.get_assignments_with_ids_for_range(d, d)

    repository.move_assignment(row["id"], BASE_NINH_BINH)

    assert repository.find_assignment(d, BASE_HANOI, "0001") is None
    moved = repository.find_assignment(d, BASE_NINH_BINH, "0001")
    assert moved is not None
    assert moved["id"] == row["id"]


def test_move_assignment_raises_if_target_already_taken(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    d = date(2026, 9, 7)
    repository.assign_staff(d, BASE_HANOI, "0001")
    repository.assign_staff(d, BASE_NINH_BINH, "0001")
    hanoi_row = [
        r for r in repository.get_assignments_with_ids_for_range(d, d) if r["base"] == BASE_HANOI
    ][0]

    with pytest.raises(repository.DuplicateAssignmentError):
        repository.move_assignment(hanoi_row["id"], BASE_NINH_BINH)


def test_assign_staff_persists_is_half_day(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    d = date(2026, 9, 12)  # Saturday
    repository.assign_staff(d, BASE_HANOI, "0001", is_half_day=True)

    [row] = repository.get_assignments_with_ids_for_range(d, d)
    assert row["is_half_day"] is True

    found = repository.find_assignment(d, BASE_HANOI, "0001")
    assert found["is_half_day"] is True


def test_move_assignment_preserves_is_half_day(temp_db):
    repository.upsert_staff_df(_sample_staff_df())
    d = date(2026, 9, 12)
    repository.assign_staff(d, BASE_HANOI, "0001", is_half_day=True)
    [row] = repository.get_assignments_with_ids_for_range(d, d)

    repository.move_assignment(row["id"], BASE_NINH_BINH)

    moved = repository.find_assignment(d, BASE_NINH_BINH, "0001")
    assert moved["is_half_day"] is True
