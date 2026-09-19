"""Outputs tab: pick a month + year, generate the "Bảng phân công trực"
Word document from Assignment data (app.logic.roster_export), preview it as
two tables (one per cơ sở), and download the generated .docx.
"""

from __future__ import annotations

import calendar
import io
from datetime import date, datetime

import pandas as pd
import streamlit as st

from app import repository
from app.config import BASE_HANOI, BASE_NINH_BINH
from app.docx_export import SECTION_HEADINGS, build_roster_document
from app.logic.roster_export import RosterRow, build_roster_rows

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_RESULT_KEY = "outputs_roster_result"


def _select_month_year() -> tuple[int, int]:
    today = date.today()
    years = list(range(today.year - 3, today.year + 2))
    col_year, col_month = st.columns([1, 1])
    with col_year:
        year = st.selectbox("Năm", years, index=years.index(today.year), key="outputs_roster_year")
    with col_month:
        month = st.selectbox(
            "Tháng",
            list(range(1, 13)),
            index=today.month - 1,
            format_func=lambda m: f"Tháng {m:02d}",
            key="outputs_roster_month",
        )
    return year, month


def _rows_to_df(rows: list[RosterRow]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Ngày": f"{r.day.day}/{r.day.month}",
                "Thứ": r.weekday_label,
                "Trực 24/24 (ĐH)": r.dai_hoc_24,
                "Trực 12/24 (ĐH)": r.dai_hoc_12,
                "Trực 24/24 (CĐ)": r.cao_dang_24,
                "Trực 12/24 (CĐ)": r.cao_dang_12,
                "Ghi chú": r.ghi_chu,
            }
            for r in rows
        ]
    )


def _generate(year: int, month: int) -> None:
    last_day = calendar.monthrange(year, month)[1]
    assignments = repository.get_assignments_for_range(date(year, month, 1), date(year, month, last_day))
    staff_by_id = repository.get_all_staff_by_id()
    holidays = repository.get_all_holidays()
    tables = {
        base: build_roster_rows(assignments, staff_by_id, base, year, month, holidays)
        for base in (BASE_HANOI, BASE_NINH_BINH)
    }
    st.session_state[_RESULT_KEY] = {
        "year": year,
        "month": month,
        "tables": tables,
        "generated_at": datetime.now(),
    }


def render() -> None:
    st.subheader("Tạo bảng phân công trực")
    year, month = _select_month_year()

    if st.button("Tạo báo cáo", key="outputs_roster_generate"):
        _generate(year, month)

    result = st.session_state.get(_RESULT_KEY)
    if not result:
        st.info("Chọn tháng/năm rồi bấm \"Tạo báo cáo\" để xem trước và tải file.")
        return

    st.caption(f"Xem trước: bảng phân công trực tháng {result['month']:02d} năm {result['year']}")
    for base in (BASE_HANOI, BASE_NINH_BINH):
        st.markdown(f"**{SECTION_HEADINGS[base]}**")
        st.dataframe(_rows_to_df(result["tables"][base]), hide_index=True)

    doc = build_roster_document(result["month"], result["year"], result["tables"], result["generated_at"])
    buffer = io.BytesIO()
    doc.save(buffer)
    st.download_button(
        "Tải file .docx",
        data=buffer.getvalue(),
        file_name=f"BangPhanCongTruc_T{result['month']:02d}_{result['year']}.docx",
        mime=_DOCX_MIME,
        key="outputs_roster_download",
    )
