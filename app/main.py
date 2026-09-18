"""Streamlit entrypoint: Data / Calendar / Outputs tabs."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from app import repository
from app.db import init_db
from app.ui import calendar_page, data_page, outputs_page, stats_page
from app.ui.access import is_view_only

st.set_page_config(page_title="Trực dược", layout="wide")
init_db()
repository.sync_ninh_binh_base_on_startup()

col_title, col_refresh = st.columns([6, 1])
with col_title:
    st.title("Quản lý phân lịch trực")
with col_refresh:
    st.write("")  # vertical spacer to align the button with the title
    if st.button(
        "🔄 Làm mới dữ liệu",
        help=(
            "Xóa cache và tải lại dữ liệu mới nhất từ database. Dùng khi dữ liệu vừa được "
            "thay đổi từ bên ngoài app (script migrate, sửa trực tiếp DB...) mà chưa thấy "
            "cập nhật -- dữ liệu sửa qua các nút Lưu trong app đã tự làm mới, không cần bấm."
        ),
    ):
        st.cache_data.clear()
        repository.sync_ninh_binh_base_on_startup.clear()
        st.rerun()

if is_view_only():
    st.info("👁️ Chế độ chỉ xem — không thể chỉnh sửa dữ liệu hoặc lịch trực.")

# A plain conditional (not st.tabs) is used here on purpose: st.tabs renders
# every tab's content into the DOM up front (hidden via CSS), and the
# iframe-based calendar component measures a 0 height while hidden and
# never recalculates once its tab becomes visible. Rendering only the
# selected page avoids mounting the calendar while hidden.
page = st.radio(
    "Trang",
    ["Dữ liệu", "Lịch trực", "Thống kê điểm trực", "Xuất file"],
    horizontal=True,
    label_visibility="collapsed",
)

if page == "Dữ liệu":
    data_page.render()
elif page == "Lịch trực":
    calendar_page.render()
elif page == "Thống kê điểm trực":
    stats_page.render()
else:
    outputs_page.render()
