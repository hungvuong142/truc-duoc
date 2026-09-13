"""One-time (idempotent) migration: seed data/*.xlsx -> data/app.db (SQLite).

Safe to re-run: rows are upserted on primary key, so running this twice
does not create duplicates. The source .xlsx files are only read, never
modified.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DUTY_WEIGHT_XLSX, STAFF_XLSX, WEEKEND_HALF_DUTY_CODE
from app.db import get_session, init_db
from app.models import DutyWeight, Staff


def _clean_phone(raw) -> str | None:
    """Excel stores phone numbers as plain integers, dropping any leading
    zero. Vietnamese mobile numbers are 10 digits starting with 0, so a
    9-digit value is assumed to be missing that leading zero."""
    if pd.isna(raw):
        return None
    digits = str(int(raw))
    if len(digits) == 9:
        digits = "0" + digits
    return digits


def _format_bmo_id(raw) -> str:
    return f"{int(raw):04d}"


def migrate_staff(session) -> int:
    df = pd.read_excel(STAFF_XLSX, sheet_name="Sheet1")
    df = df.dropna(subset=["bmo_id"])

    count = 0
    for _, row in df.iterrows():
        bmo_id = _format_bmo_id(row["bmo_id"])
        staff = session.get(Staff, bmo_id)
        if staff is None:
            staff = Staff(bmo_id=bmo_id)
            session.add(staff)

        staff.ho_va_ten = str(row["ho_va_ten"]).strip()
        staff.tuoi = int(row["tuoi"]) if pd.notna(row["tuoi"]) else None
        staff.gioi_tinh = row["gioi_tinh"] if pd.notna(row["gioi_tinh"]) else None
        staff.trinh_do = row["trinh_do"] if pd.notna(row["trinh_do"]) else None
        staff.vi_tri = str(row["vi_tri"]).strip()
        staff.so_dien_thoai = _clean_phone(row["so_dien_thoai"])
        staff.mang_thai = bool(pd.notna(row["mang_thai"]))
        staff.sinh_de = bool(pd.notna(row["sinh_de"]))
        staff.ghi_chu = row["ghi_chu"] if pd.notna(row["ghi_chu"]) else None
        staff.ninh_binh_base = bool(pd.notna(row["ninh_binh_base"]))
        staff.is_active = True
        count += 1
    return count


# The source xlsx's descriptions are in English; translated here (keyed by
# the normalized duty_type) since the app is used in Vietnamese. The xlsx
# itself is left untouched.
DUTY_TYPE_DESCRIPTIONS_VI = {
    "normal_day": "Ngày thường, từ thứ Hai đến thứ Năm, không tính ngày lễ",
    "friday": "Thứ Sáu, không tính ngày lễ",
    "saturday": "Thứ Bảy, không tính ngày lễ (không có ngày nghỉ bù)",
    "sunday": "Chủ nhật, không tính ngày lễ (có ngày nghỉ bù sau đó)",
    "holidays": "Ngày lễ, trực 24 giờ, nhân lực ít hơn nhiều",
    "exchange_base": (
        "Nhân viên đang làm việc tại cơ sở Hà Nội được điều động sang "
        "cơ sở Ninh Bình (khoảng cách xa, tốn thời gian di chuyển)"
    ),
}


def migrate_duty_weights(session) -> int:
    df = pd.read_excel(DUTY_WEIGHT_XLSX, sheet_name="Sheet1")
    df = df.dropna(subset=["duty_type"])

    count = 0
    for _, row in df.iterrows():
        duty_code = int(row["duty_code"])
        duty_weight = session.get(DutyWeight, duty_code)
        if duty_weight is None:
            duty_weight = DutyWeight(duty_code=duty_code)
            session.add(duty_weight)

        # Normalize the source sheet's "sartuday" typo without touching the
        # xlsx file itself.
        duty_type = str(row["duty_type"]).strip()
        if duty_type == "sartuday":
            duty_type = "saturday"

        duty_weight.duty_type = duty_type
        duty_weight.description = DUTY_TYPE_DESCRIPTIONS_VI.get(
            duty_type, row["description"] if pd.notna(row["description"]) else None
        )
        duty_weight.duty_weight = float(row["duty_weight"]) if pd.notna(row["duty_weight"]) else None
        duty_weight.multiplier = float(row["multiplier"]) if pd.notna(row["multiplier"]) else None
        count += 1
    return count


def migrate_extra_duty_types(session) -> int:
    """Duty types with no corresponding row in the source xlsx -- added
    directly here instead."""
    extras = [
        {
            "duty_code": WEEKEND_HALF_DUTY_CODE,
            "duty_type": "weekend_half",
            "description": (
                "Trực nửa ngày thứ Bảy hoặc nửa ngày Chủ nhật -- trọng số bằng "
                "một nửa trọng số ngày đó nếu trực cả ngày"
            ),
            "duty_weight": None,
            "multiplier": 0.5,
        },
    ]
    count = 0
    for row in extras:
        duty_weight = session.get(DutyWeight, row["duty_code"])
        if duty_weight is None:
            duty_weight = DutyWeight(duty_code=row["duty_code"])
            session.add(duty_weight)
        duty_weight.duty_type = row["duty_type"]
        duty_weight.description = row["description"]
        duty_weight.duty_weight = row["duty_weight"]
        duty_weight.multiplier = row["multiplier"]
        count += 1
    return count


def main() -> None:
    init_db()
    with get_session() as session:
        n_staff = migrate_staff(session)
        n_weights = migrate_duty_weights(session) + migrate_extra_duty_types(session)
    print(f"Migrated {n_staff} staff rows and {n_weights} duty-weight rows into the database.")


if __name__ == "__main__":
    main()
