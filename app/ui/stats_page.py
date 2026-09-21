"""'Thống kê' tab: two sheets -- accumulated duty-weight totals per month,
and a count of how many times each staff member was assigned per weekday."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import pandas as pd
import streamlit as st

from app import repository
from app.config import WEEKDAY_LABELS
from app.logic.weights import compute_single_month_weight

_TRINH_DO_ORDER = {"Đại học": 0, "Cao đẳng": 1}


def _format_half(value: float) -> str:
    """Render a weekday-duty count that may include half-day (half_day)
    occurrences, e.g. 0.5 -> '1/2', 1.5 -> '1 1/2', 2.0 -> '2'."""
    whole, frac = divmod(round(value * 2), 2)
    if frac == 0:
        return str(whole)
    if whole == 0:
        return "0,5"
    return f"{whole} + 0,5"


def _month_col(year: int, month: int) -> str:
    return f"{month:02d}/{year:04d}"


def _select_year_months(key_prefix: str) -> list[tuple[int, int]]:
    today = date.today()
    years = list(range(today.year - 3, today.year + 2))
    col_year, col_months = st.columns([1, 3])
    with col_year:
        year = st.selectbox("Năm", years, index=years.index(today.year), key=f"{key_prefix}_year")
    with col_months:
        selected_months = st.multiselect(
            "Chọn (các) tháng",
            options=list(range(1, 13)),
            default=[today.month],
            format_func=lambda m: f"Tháng {m:02d}",
            key=f"{key_prefix}_months",
        )
    return [(year, m) for m in sorted(selected_months)]


def _render_weight_stats() -> None:
    year_months = _select_year_months("stats")
    if not year_months:
        st.info("Chọn ít nhất một tháng để xem thống kê.")
        return

    staff_by_id = repository.get_all_staff_by_id(active_only=True)
    all_staff = list(staff_by_id.values())
    holidays = repository.get_all_holidays()
    duty_weights = repository.get_duty_weights()
    ninh_binh_months = repository.get_ninh_binh_assignment_months()
    assignments = repository.get_assignments_for_year_months(year_months)
    # A DSĐH covering a Cao đẳng slot (see calendar_page._assign_dialog) is
    # grouped under Cao đẳng here for any month where they have such an
    # assignment -- their own trinh_do field is untouched.
    cao_dang_cover_ids = {a.staff_id for a in assignments if a.is_cao_dang_cover}

    if not all_staff:
        st.info("Chưa có nhân viên đang làm việc để thống kê.")
        return

    rows = []
    for staff in all_staff:
        effective_trinh_do = "Cao đẳng" if staff.bmo_id in cao_dang_cover_ids else staff.trinh_do
        row = {
            "bmo_id": staff.bmo_id,
            "ho_va_ten": staff.ho_va_ten, 
            "trinh_do": effective_trinh_do,
            "vi_tri": staff.vi_tri,
        }
        total_selected = 0.0
        for year_, month_ in year_months:
            weight = compute_single_month_weight(
                staff.bmo_id, year_, month_, assignments, holidays, duty_weights, ninh_binh_months
            )
            row[_month_col(year_, month_)] = weight
            total_selected += weight
        row["_sort_total"] = total_selected
        row["_sort_trinh_do"] = _TRINH_DO_ORDER.get(effective_trinh_do, 2)
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
        "vi_tri": st.column_config.TextColumn("Vị trí"),
    }
    for year_, month_ in year_months:
        column_config[_month_col(year_, month_)] = st.column_config.NumberColumn(
            f"Tháng {month_:02d}/{year_}", format="%.2f"
        )

    st.dataframe(df, hide_index=True, column_config=column_config)
    st.caption("💡 Bấm vào tiêu đề cột để sắp xếp lại theo cột đó (tăng/giảm dần).")


def _build_weekday_df(year_months: list[tuple[int, int]], all_staff: list, assignments: list) -> pd.DataFrame:
    """One row per (month, staff) with that month's own per-weekday counter
    (a half_day duty counts 0.5) -- months are never pooled together. A DSĐH
    covering a Cao đẳng slot is grouped under Cao đẳng for the months where
    they have such an assignment; their trinh_do field is untouched."""
    selected_set = set(year_months)
    counts: dict[tuple[int, int, str], list[float]] = defaultdict(lambda: [0.0] * 7)
    cover_keys: set[tuple[int, int, str]] = set()
    for a in assignments:
        year_month = (a.duty_date.year, a.duty_date.month)
        if year_month not in selected_set:
            continue
        key = (*year_month, a.staff_id)
        counts[key][a.duty_date.weekday()] += 0.5 if a.is_half_day else 1.0
        if a.is_cao_dang_cover:
            cover_keys.add(key)

    rows = []
    for year_, month_ in year_months:
        for staff in all_staff:
            key = (year_, month_, staff.bmo_id)
            day_counts = counts.get(key, [0.0] * 7)
            total = sum(day_counts)
            effective_trinh_do = "Cao đẳng" if key in cover_keys else staff.trinh_do
            row = {
                "bmo_id": staff.bmo_id,
                "ho_va_ten": staff.ho_va_ten, 
                "trinh_do": effective_trinh_do,
                "vi_tri": staff.vi_tri,
                "thang": _month_col(year_, month_), 
            }
            row.update({label: _format_half(c) for label, c in zip(WEEKDAY_LABELS, day_counts)})
            row["Tổng"] = _format_half(total)
            row["_sort_month"] = year_ * 100 + month_
            row["_sort_total"] = total
            row["_sort_trinh_do"] = _TRINH_DO_ORDER.get(effective_trinh_do, 2)
            rows.append(row)

    return pd.DataFrame(rows).sort_values(
        ["_sort_month", "_sort_trinh_do", "_sort_total"], ascending=[True, True, False]
    ).drop(columns=["_sort_month", "_sort_trinh_do", "_sort_total"]).reset_index(drop=True)


def _render_weekday_stats() -> None:
    year_months = _select_year_months("weekday_stats")
    if not year_months:
        st.info("Chọn ít nhất một tháng để xem thống kê.")
        return

    all_staff = list(repository.get_all_staff_by_id(active_only=True).values())
    if not all_staff:
        st.info("Chưa có nhân viên đang làm việc để thống kê.")
        return

    assignments = repository.get_assignments_for_year_months(year_months)
    df = _build_weekday_df(year_months, all_staff, assignments)

    column_config = {
        "bmo_id": st.column_config.TextColumn("Mã NV"),
        "ho_va_ten": st.column_config.TextColumn("Họ và tên"),
        "trinh_do": st.column_config.TextColumn("Trình độ"),
        "vi_tri": st.column_config.TextColumn("Vị trí"),
        "thang": st.column_config.TextColumn("Tháng"),
        "Tổng": st.column_config.TextColumn("Tổng"),
    }
    for label in WEEKDAY_LABELS:
        column_config[label] = st.column_config.TextColumn(label)

    st.dataframe(df, hide_index=True, column_config=column_config)
    st.caption("💡 Mỗi dòng là một tháng của một nhân viên. Bấm vào tiêu đề cột để sắp xếp lại (tăng/giảm dần).")


def render() -> None:
    st.subheader("Thống kê")
    tab_weight, tab_weekday = st.tabs(["Điểm trực", "Trực theo ngày"])
    with tab_weight:
        _render_weight_stats()
    with tab_weekday:
        _render_weekday_stats()
