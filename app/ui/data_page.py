"""Data tab: spreadsheet-style editors for staff, duty weights, holidays."""

from __future__ import annotations

from datetime import date

import streamlit as st

from app import repository
from app.config import GIOI_TINH_OPTIONS, TRINH_DO_OPTIONS
from app.ui.access import is_view_only
from app.ui.xlsx_io import render_template_download_and_upload

STAFF_TEMPLATE_COLUMNS = [
    "bmo_id", "ho_va_ten", "tuoi", "gioi_tinh", "trinh_do", "vi_tri",
    "so_dien_thoai", "mang_thai", "sinh_de", "ghi_chu", "ninh_binh_base", "is_active",
]
STAFF_TEMPLATE_SAMPLE = {
    "bmo_id": "0001", "ho_va_ten": "Nguyễn Văn A", "tuoi": 30, "gioi_tinh": "Nam",
    "trinh_do": "Cao đẳng", "vi_tri": "Hồ sơ", "so_dien_thoai": "0123456789",
    "mang_thai": False, "sinh_de": False, "ghi_chu": "", "ninh_binh_base": False,
    "is_active": True,
}

DUTY_WEIGHT_TEMPLATE_COLUMNS = ["duty_code", "duty_type", "description", "duty_weight", "multiplier"]
DUTY_WEIGHT_TEMPLATE_SAMPLE = {
    "duty_code": 1, "duty_type": "normal_day",
    "description": "Ngày thường, từ thứ Hai đến thứ Năm, không tính ngày lễ",
    "duty_weight": 1.0, "multiplier": None,
}

HOLIDAY_TEMPLATE_COLUMNS = ["name", "is_recurring", "month", "day", "year"]
HOLIDAY_TEMPLATE_SAMPLE = {
    "name": "Quốc khánh", "is_recurring": True, "month": 9, "day": 2, "year": None,
}


def _render_staff_editor() -> None:
    st.subheader("Nhân viên")
    view_only = is_view_only()
    if not view_only:
        render_template_download_and_upload(
            template_filename="MauNhapDuLieu_NhanVien.xlsx",
            columns=STAFF_TEMPLATE_COLUMNS,
            sample_row=STAFF_TEMPLATE_SAMPLE,
            importer=repository.import_staff_df,
            key_prefix="staff",
        )
    df = repository.get_staff_df()
    column_config = {
        "bmo_id": st.column_config.TextColumn("Mã NV", help="Để trống để tự sinh mã mới"),
        "ho_va_ten": st.column_config.TextColumn("Họ và tên", required=True),
        "tuoi": st.column_config.NumberColumn("Tuổi", min_value=18, max_value=80, step=1),
        "gioi_tinh": st.column_config.SelectboxColumn("Giới tính", options=list(GIOI_TINH_OPTIONS)),
        "trinh_do": st.column_config.SelectboxColumn("Trình độ", options=list(TRINH_DO_OPTIONS)),
        "vi_tri": st.column_config.TextColumn("Vị trí", required=True),
        "so_dien_thoai": st.column_config.TextColumn("Số điện thoại"),
        "mang_thai": st.column_config.CheckboxColumn("Mang thai"),
        "sinh_de": st.column_config.CheckboxColumn("Sau sinh"),
        "ghi_chu": st.column_config.TextColumn("Ghi chú"),
        "ninh_binh_base": st.column_config.CheckboxColumn(
            "Cơ sở Ninh Bình", help="Tính tự động từ sheet 'Đi cơ sở Ninh Bình' theo tháng hiện tại."
        ),
        "is_active": st.column_config.CheckboxColumn("Đang làm việc"),
    }
    if view_only:
        st.dataframe(df, hide_index=True, column_config=column_config)
        return

    edited = st.data_editor(
        df, key="staff_editor", num_rows="dynamic", hide_index=True, column_config=column_config,
        disabled=["ninh_binh_base"],
    )
    st.caption("💡 Để xóa một dòng: bấm chọn ô đầu dòng đó rồi nhấn phím Delete, sau đó bấm Lưu.")
    if st.button("Lưu dữ liệu nhân viên", key="save_staff"):
        repository.upsert_staff_df(edited)
        st.success("Đã lưu dữ liệu nhân viên.")
        st.rerun()


def _render_ninh_binh_editor() -> None:
    st.subheader("Đi cơ sở Ninh Bình")
    st.caption(
        "Tích chọn nhân viên đi cơ sở Ninh Bình theo từng tháng. Cột 'Cơ sở Ninh Bình' ở sheet "
        "Nhân viên phản ánh tháng hiện tại của bảng này (tính lại ngay sau khi lưu, hoặc mỗi khi "
        "app khởi động lại)."
    )
    view_only = is_view_only()
    today = date.today()
    col_year, col_month = st.columns(2)
    with col_year:
        year = st.number_input(
            "Năm", min_value=today.year - 3, max_value=today.year + 2,
            value=today.year, step=1, key="ninh_binh_year",
        )
    with col_month:
        month = st.selectbox(
            "Tháng", options=list(range(1, 13)), index=today.month - 1,
            format_func=lambda m: f"Tháng {m:02d}", key="ninh_binh_month",
        )
    year, month = int(year), int(month)

    df = repository.get_ninh_binh_assignments_df(year, month)
    if df.empty:
        st.info("Chưa có nhân viên đang làm việc để phân công.")
        return

    column_config = {
        "bmo_id": st.column_config.TextColumn("Mã NV"),
        "ho_va_ten": st.column_config.TextColumn("Họ và tên"),
        "trinh_do": st.column_config.TextColumn("Trình độ"),
        "vi_tri": st.column_config.TextColumn("Vị trí"),
        "di_ninh_binh": st.column_config.CheckboxColumn("Đi Ninh Bình"),
    }
    if view_only:
        st.dataframe(df, hide_index=True, column_config=column_config)
        return

    edited = st.data_editor(
        df, key=f"ninh_binh_editor_{year}_{month}", hide_index=True, column_config=column_config,
        disabled=["bmo_id", "ho_va_ten", "trinh_do", "vi_tri"],
    )
    if st.button("Lưu danh sách đi Ninh Bình", key="save_ninh_binh"):
        selected_ids = edited.loc[edited["di_ninh_binh"], "bmo_id"].tolist()
        repository.save_ninh_binh_assignments(year, month, selected_ids)
        st.success(f"Đã lưu danh sách đi Ninh Bình tháng {month:02d}/{year}.")
        st.rerun()


def _render_duty_weights_editor() -> None:
    st.subheader("Trọng số trực")
    view_only = is_view_only()
    if not view_only:
        render_template_download_and_upload(
            template_filename="MauNhapDuLieu_TrongSoTruc.xlsx",
            columns=DUTY_WEIGHT_TEMPLATE_COLUMNS,
            sample_row=DUTY_WEIGHT_TEMPLATE_SAMPLE,
            importer=repository.import_duty_weights_df,
            key_prefix="duty_weights",
        )
    df = repository.get_duty_weights_df()
    column_config = {
        "duty_code": st.column_config.NumberColumn("Mã", required=True, step=1),
        "duty_type": st.column_config.TextColumn("Loại trực", required=True),
        "description": st.column_config.TextColumn("Mô tả"),
        "duty_weight": st.column_config.NumberColumn("Trọng số", step=0.25),
        "multiplier": st.column_config.NumberColumn("Hệ số nhân", step=0.05),
    }
    if view_only:
        st.dataframe(df, hide_index=True, column_config=column_config)
        return

    edited = st.data_editor(
        df, key="duty_weights_editor", num_rows="dynamic", hide_index=True, column_config=column_config
    )
    st.caption("💡 Để xóa một dòng: bấm chọn ô đầu dòng đó rồi nhấn phím Delete, sau đó bấm Lưu.")
    if st.button("Lưu trọng số trực", key="save_duty_weights"):
        repository.upsert_duty_weights_df(edited)
        st.success("Đã lưu trọng số trực.")
        st.rerun()


def _render_holidays_editor() -> None:
    st.subheader("Ngày lễ / nghỉ")
    view_only = is_view_only()
    if not view_only:
        render_template_download_and_upload(
            template_filename="MauNhapDuLieu_NgayLe.xlsx",
            columns=HOLIDAY_TEMPLATE_COLUMNS,
            sample_row=HOLIDAY_TEMPLATE_SAMPLE,
            importer=repository.import_holidays_df,
            key_prefix="holidays",
        )

    st.markdown("**Lễ định kỳ hằng năm**")
    recurring_df = repository.get_holidays_df(is_recurring=True)
    recurring_column_config = {
        "id": None,
        "name": st.column_config.TextColumn("Tên ngày lễ", required=True, width="medium"),
        "month": st.column_config.NumberColumn(
            "Tháng", min_value=1, max_value=12, step=1, required=True, width="small"
        ),
        "day": st.column_config.NumberColumn(
            "Ngày", min_value=1, max_value=31, step=1, required=True, width="small"
        ),
    }
    if view_only:
        st.dataframe(recurring_df, hide_index=True, column_config=recurring_column_config, width="content")
    else:
        edited_recurring = st.data_editor(
            recurring_df, key="recurring_holidays_editor", num_rows="dynamic", hide_index=True,
            width="content", column_config=recurring_column_config,
        )
        st.caption("💡 Để xóa một dòng: bấm chọn ô đầu dòng đó rồi nhấn phím Delete, sau đó bấm Lưu.")
        if st.button("Lưu lễ định kỳ", key="save_recurring_holidays"):
            repository.sync_holidays_df(edited_recurring, is_recurring=True)
            st.success("Đã lưu lễ định kỳ.")
            st.rerun()

    st.markdown("**Nghỉ lễ chỉ định (theo năm cụ thể)**")
    manual_df = repository.get_holidays_df(is_recurring=False)
    manual_column_config = {
        "id": None,
        "name": st.column_config.TextColumn("Tên", required=True, width="medium"),
        "month": st.column_config.NumberColumn(
            "Tháng", min_value=1, max_value=12, step=1, required=True, width="small"
        ),
        "day": st.column_config.NumberColumn(
            "Ngày", min_value=1, max_value=31, step=1, required=True, width="small"
        ),
        "year": st.column_config.NumberColumn(
            "Năm", min_value=2000, max_value=2100, step=1, required=True, width="small"
        ),
    }
    if view_only:
        st.dataframe(manual_df, hide_index=True, column_config=manual_column_config, width="content")
        return

    edited_manual = st.data_editor(
        manual_df, key="manual_holidays_editor", num_rows="dynamic", hide_index=True,
        width="content", column_config=manual_column_config,
    )
    st.caption("💡 Để xóa một dòng: bấm chọn ô đầu dòng đó rồi nhấn phím Delete, sau đó bấm Lưu.")
    if st.button("Lưu nghỉ chỉ định", key="save_manual_holidays"):
        repository.sync_holidays_df(edited_manual, is_recurring=False)
        st.success("Đã lưu nghỉ chỉ định.")
        st.rerun()


def render() -> None:
    tab_staff, tab_ninh_binh, tab_weights, tab_holidays = st.tabs(
        ["Nhân viên", "Đi cơ sở Ninh Bình", "Trọng số trực", "Ngày lễ"]
    )
    with tab_staff:
        _render_staff_editor()
    with tab_ninh_binh:
        _render_ninh_binh_editor()
    with tab_weights:
        _render_duty_weights_editor()
    with tab_holidays:
        _render_holidays_editor()
