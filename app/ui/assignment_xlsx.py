"""Calendar page panel: export duty assignments to Excel (one month or
everything) and import them back from a file.

Importing is two-step (check -> preview -> confirm) so a wrong file can't
silently overwrite the schedule: only slots (date + base) the file mentions
are touched -- replaced if they already exist, added if not."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from app import repository
from app.config import BASE_SHORT_LABELS
from app.logic import assignment_io as aio
from app.ui.access import is_view_only
from app.ui.xlsx_io import make_xlsx_bytes

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_SCOPE_MONTH = "Theo tháng"
_SCOPE_ALL = "Toàn bộ dữ liệu trực"
_PLAN_KEY = "asg_import_plan"
_MAX_ERRORS_SHOWN = 20

_TEMPLATE_ROWS = [
    {
        aio.COL_DATE: date(2026, 1, 1), aio.COL_BASE: "CSHN",
        aio.COL_FULL: "0001 - Nguyễn Văn A; 0002 - Trần Thị B", aio.COL_HALF: "0003 - Lê Văn C",
        aio.COL_COVER: "0002 - Trần Thị B",
    },
    {
        aio.COL_DATE: date(2026, 1, 1), aio.COL_BASE: "CSNB",
        aio.COL_FULL: "0004", aio.COL_HALF: "", aio.COL_COVER: "",
    },
]


def _template_bytes() -> bytes:
    return make_xlsx_bytes(pd.DataFrame(_TEMPLATE_ROWS), aio.COLUMNS)


def _render_export(year: int, month: int) -> None:
    st.markdown("**Tải dữ liệu lịch trực**")
    scope = st.radio(
        "Phạm vi tải dữ liệu", [_SCOPE_MONTH, _SCOPE_ALL], horizontal=True, key="asg_export_scope",
        label_visibility="collapsed",
    )
    export_year, export_month = year, month
    if scope == _SCOPE_MONTH:
        # Keyed by the viewed month so the pickers follow the calendar when
        # the user navigates to another month.
        col_year, col_month = st.columns(2)
        with col_year:
            export_year = int(st.number_input(
                "Năm", min_value=2000, max_value=2100, value=year, step=1, key=f"asg_export_year_{year}_{month}"
            ))
        with col_month:
            export_month = st.selectbox(
                "Tháng", list(range(1, 13)), index=month - 1,
                format_func=lambda m: f"Tháng {m:02d}", key=f"asg_export_month_{year}_{month}",
            )

    staff_by_id = repository.get_all_staff_by_id()

    def build_current_data() -> bytes:
        if scope == _SCOPE_MONTH:
            assignments = repository.get_assignments_for_months(export_year, export_month, 0)
        else:
            assignments = repository.get_all_assignments()
        return make_xlsx_bytes(pd.DataFrame(aio.build_export_rows(assignments, staff_by_id)), aio.COLUMNS)

    file_name = (
        f"LichTruc_{export_year}_{export_month:02d}.xlsx" if scope == _SCOPE_MONTH else "LichTruc_toan_bo.xlsx"
    )
    # Callables are evaluated on click only, so opening the calendar doesn't
    # query/serialize the schedule on every rerun.
    col_template, col_current = st.columns(2)
    with col_template:
        st.download_button(
            "Tải file mẫu", data=_template_bytes, file_name="MauNhapDuLieu_LichTruc.xlsx",
            mime=_XLSX_MIME, key="asg_template", on_click="ignore", width="stretch",
        )
    with col_current:
        st.download_button(
            "⬇️ Tải dữ liệu hiện có", data=build_current_data, file_name=file_name,
            mime=_XLSX_MIME, key="asg_export", on_click="ignore", width="stretch",
        )


def _analyze(uploaded) -> dict:
    state = {"file_id": uploaded.file_id, "errors": [], "plans": [], "blank_rows": 0}
    try:
        df = pd.read_excel(uploaded, dtype=str)
    except Exception as exc:  # unreadable/corrupt user-supplied file
        state["errors"].append(f"Không đọc được file Excel: {exc}")
        return state

    missing = [c for c in aio.COLUMNS if c != aio.COL_COVER and c not in df.columns]
    if missing:
        state["errors"].append(f"File thiếu cột: {', '.join(missing)}")
        return state

    staff_by_id = repository.get_all_staff_by_id()
    parsed = aio.parse_import_frame(df, set(staff_by_id))
    state["errors"] = parsed.errors
    state["blank_rows"] = parsed.blank_rows
    if parsed.errors or not parsed.slots:
        return state

    dates = [duty_date for duty_date, _ in parsed.slots]
    existing = repository.get_assignments_for_range(min(dates), max(dates))
    plans, conflicts = aio.plan_import(
        parsed.slots, existing, {i: s.ho_va_ten for i, s in staff_by_id.items()}
    )
    state["plans"] = plans
    state["errors"] = conflicts
    return state


def _render_preview(state: dict) -> None:
    errors = state["errors"]
    if errors:
        lines = [f"- {e}" for e in errors[:_MAX_ERRORS_SHOWN]]
        if len(errors) > _MAX_ERRORS_SHOWN:
            lines.append(f"- ... và {len(errors) - _MAX_ERRORS_SHOWN} lỗi khác")
        st.error("Không thể nạp vì file có lỗi. Hãy sửa file rồi tải lên lại:\n\n" + "\n".join(lines))
        return

    plans = state["plans"]
    if not plans:
        st.info("File không có dòng dữ liệu nào để nạp.")
        return
    if state["blank_rows"]:
        st.caption(f"Bỏ qua {state['blank_rows']} dòng không có DS trực.")

    n_new = sum(p.status == aio.STATUS_NEW for p in plans)
    n_override = sum(p.status == aio.STATUS_OVERRIDE for p in plans)
    n_unchanged = sum(p.status == aio.STATUS_UNCHANGED for p in plans)
    col_new, col_override, col_unchanged = st.columns(3)
    col_new.metric("Ngày/cơ sở thêm mới", n_new)
    col_override.metric("Ngày/cơ sở ghi đè", n_override)
    col_unchanged.metric("Không thay đổi", n_unchanged)

    changed = [p for p in plans if p.status != aio.STATUS_UNCHANGED]
    if not changed:
        st.info("Dữ liệu trong file đã khớp với dữ liệu hiện có, không có gì để nạp.")
        return

    status_labels = {aio.STATUS_NEW: "Thêm mới", aio.STATUS_OVERRIDE: "Ghi đè"}
    st.dataframe(
        pd.DataFrame([
            {
                "Ngày": p.duty_date.strftime("%d/%m/%Y"),
                "Cơ sở": BASE_SHORT_LABELS.get(p.base, p.base),
                "Thao tác": status_labels[p.status],
                "Số lượt trực hiện có": p.existing_count,
                "Số lượt trực trong file": len(p.entries),
            }
            for p in changed
        ]),
        hide_index=True,
    )
    if n_override:
        st.warning(
            f"{n_override} ngày/cơ sở đã có dữ liệu sẽ bị thay hoàn toàn bằng dữ liệu trong file. "
            "Các ngày/cơ sở không có trong file được giữ nguyên."
        )
    if st.button("Xác nhận nạp dữ liệu", type="primary", key="asg_import_confirm"):
        repository.apply_assignment_import(plans)
        st.session_state.pop(_PLAN_KEY, None)
        st.session_state["_cal_flash"] = (
            f"Đã nạp lịch trực từ file: thêm mới {n_new}, ghi đè {n_override} ngày/cơ sở."
        )
        st.rerun()


def _render_import() -> None:
    st.markdown("**Nạp dữ liệu lịch trực từ file Excel**")
    st.caption(
        "Mỗi dòng là 1 ngày + 1 cơ sở (CSHN/CSNB). Các cột DS ghi mã nhân viên, cách nhau bằng dấu `;` "
        "(có thể kèm tên: `12262 - Tên`). Ngày + cơ sở đã có trong app sẽ bị ghi đè bằng nội dung file; "
        "ngày + cơ sở chưa có sẽ được thêm mới; phần còn lại giữ nguyên. Bạn sẽ được xem trước và "
        "xác nhận trước khi dữ liệu thay đổi."
    )
    uploaded = st.file_uploader(
        "Chọn file Excel lịch trực", type=["xlsx"], key="asg_import_file", label_visibility="collapsed"
    )
    if uploaded is None:
        st.session_state.pop(_PLAN_KEY, None)
        return
    if st.button("Kiểm tra file", key="asg_import_check"):
        st.session_state[_PLAN_KEY] = _analyze(uploaded)
    state = st.session_state.get(_PLAN_KEY)
    if state is not None and state["file_id"] == uploaded.file_id:
        _render_preview(state)


def render(year: int, month: int) -> None:
    with st.expander("📁 Xuất / nạp dữ liệu lịch trực"):
        _render_export(year, month)
        if not is_view_only():
            st.divider()
            _render_import()
