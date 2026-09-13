"""'Thống kê điểm trực' tab: accumulated duty-weight totals for all staff,
one column per selected month, sorted by trình độ then accumulated weight."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from app import repository
from app.logic.weights import compute_single_month_weight

_TRINH_DO_ORDER = {"Đại học": 0, "Cao đẳng": 1}


def _month_col(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def render() -> None:
    st.subheader("Thống kê điểm trực")

    today = date.today()
    years = list(range(today.year - 3, today.year + 2))
    col_year, col_months = st.columns([1, 3])
    with col_year:
        year = st.selectbox("Năm", years, index=years.index(today.year), key="stats_year")
    with col_months:
        selected_months = st.multiselect(
            "Chọn (các) tháng",
            options=list(range(1, 13)),
            default=[today.month],
            format_func=lambda m: f"Tháng {m:02d}",
            key="stats_months",
        )

    if not selected_months:
        st.info("Chọn ít nhất một tháng để xem thống kê.")
        return

    year_months = [(year, m) for m in sorted(selected_months)]

    staff_by_id = repository.get_all_staff_by_id(active_only=True)
    all_staff = list(staff_by_id.values())
    holidays = repository.get_all_holidays()
    duty_weights = repository.get_duty_weights()
    assignments = repository.get_assignments_for_year_months(year_months)

    if not all_staff:
        st.info("Chưa có nhân viên đang làm việc để thống kê.")
        return

    rows = []
    for staff in all_staff:
        row = {"bmo_id": staff.bmo_id, "ho_va_ten": staff.ho_va_ten, "trinh_do": staff.trinh_do}
        total_selected = 0.0
        for year_, month_ in year_months:
            weight = compute_single_month_weight(
                staff.bmo_id, year_, month_, assignments, staff_by_id, holidays, duty_weights
            )
            row[_month_col(year_, month_)] = weight
            total_selected += weight
        row["_sort_total"] = total_selected
        row["_sort_trinh_do"] = _TRINH_DO_ORDER.get(staff.trinh_do, 2)
        rows.append(row)

    df = pd.DataFrame(rows).sort_values(
        ["_sort_trinh_do", "_sort_total"], ascending=[True, False]
    ).drop(columns=["_sort_trinh_do", "_sort_total"]).reset_index(drop=True)

    avg_lines = []
    for year_, month_ in year_months:
        col = _month_col(year_, month_)
        for trinh_do in ("Đại học", "Cao đẳng"):
            peers = df[df["trinh_do"] == trinh_do]
            avg = float(peers[col].mean()) if not peers.empty else 0.0
            avg_lines.append(f"Tháng {month_:02d}/{year_} — TB {trinh_do}: **{avg:.2f}** điểm")
    st.caption(" · ".join(avg_lines))

    column_config = {
        "bmo_id": st.column_config.TextColumn("Mã NV"),
        "ho_va_ten": st.column_config.TextColumn("Họ và tên"),
        "trinh_do": st.column_config.TextColumn("Trình độ"),
    }
    for year_, month_ in year_months:
        column_config[_month_col(year_, month_)] = st.column_config.NumberColumn(
            f"Tháng {month_:02d}/{year_}", format="%.2f"
        )

    st.dataframe(df, hide_index=True, column_config=column_config)
    st.caption("💡 Bấm vào tiêu đề cột để sắp xếp lại theo cột đó (tăng/giảm dần).")
