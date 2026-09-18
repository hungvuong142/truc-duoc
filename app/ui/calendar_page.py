"""Calendar tab: a month grid built from native Streamlit layout (not the
streamlit-calendar component) so each day cell can be split into two
sub-cells, one per base (CSHN/CSNB), with staff sorted and colored by
trình độ and click-to-view contact info.

Cell/legend colors are explicit hex values (not the theme's primary/
secondary button styles) so the legend text always matches what's actually
rendered -- this was requested explicitly by the user, which is the one
case where custom CSS via `st.html()` + `key=`-based `.st-key-*` classes is
appropriate instead of native theming.
"""

from __future__ import annotations

import calendar as calendar_module
from collections import defaultdict
from datetime import date

import streamlit as st

from app import repository
from app.config import BASE_SHORT_LABELS, BASES, N_TRAILING_MONTHS, WEEKDAY_LABELS
from app.logic.calendar_rules import classify_position, resolve_holiday_name
from app.logic.weights import compute_monthly_weights, compute_peer_average, compute_single_month_weight
from app.repository import DuplicateAssignmentError
from app.ui.access import is_view_only

_WEEKDAY_LABELS = WEEKDAY_LABELS
_WEEKEND_WEEKDAYS = {5, 6}  # Python date.weekday(): Saturday=5, Sunday=6
_TRINH_DO_GROUPS = ("Đại học", "Cao đẳng")
_MAX_SUGGESTIONS_PER_GROUP = 5

# Explicit chip colors: same hue, Cao đẳng lighter than Đại học.
_DAI_HOC_BG = "#1D4ED8"
_DAI_HOC_TEXT = "#FFFFFF"
_CAO_DANG_BG = "#BFDBFE"
_CAO_DANG_TEXT = "#1E3A8A"

# Day-cell background highlights.
_WEEKEND_BG = "rgba(37, 99, 235, 0.08)"
_HOLIDAY_BG = "rgba(220, 38, 38, 0.12)"
_TODAY_OVERLAY = "rgba(245, 158, 11, 0.5)"  # ~50% opacity, layered on top


def _staff_label(staff) -> str:
    return f"{staff.ho_va_ten} ({staff.bmo_id}) · {staff.trinh_do or '?'}"


def _sort_key(entry: dict, staff_by_id: dict) -> tuple:
    staff = staff_by_id.get(entry["staff_id"])
    trinh_do_rank = 0 if (staff and staff.trinh_do == "Đại học") else 1
    half_day_rank = 1 if entry.get("is_half_day") else 0
    name = staff.ho_va_ten if staff else entry["staff_id"]
    return (trinh_do_rank, half_day_rank, name)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    zero_based = (year * 12 + (month - 1)) + delta
    return zero_based // 12, zero_based % 12 + 1


def _chip_key(entry_id: int, trinh_do: str | None) -> str:
    bucket = "dh" if trinh_do == "Đại học" else "cd"
    return f"chip_{bucket}_{entry_id}"


def _other_base(base: str) -> str:
    return next(b for b in BASES if b != base)


def _suggest_low_weight_staff(
    duty_date: date, staff_by_id: dict, ms_key: str, exclude_ids: set[str]
) -> None:
    """Suggestion list for the assign dialog: active staff free that day,
    grouped Đại học / Cao đẳng (same grouping as the peer-average weight
    calc), sorted by ascending accumulated weight for the assignment's
    month -- the people most in need of a duty to stay balanced. Clicking
    one adds it to the multiselect instead of typing/searching."""
    holidays = repository.get_all_holidays()
    duty_weights = repository.get_duty_weights()
    month_assignments = repository.get_assignments_for_months(duty_date.year, duty_date.month, 0)

    any_suggestion = False
    for trinh_do in _TRINH_DO_GROUPS:
        peers = [
            s for s in staff_by_id.values()
            if s.is_active and s.trinh_do == trinh_do and s.bmo_id not in exclude_ids
        ]
        if not peers:
            continue
        weighted = sorted(
            (
                (s, compute_single_month_weight(
                    s.bmo_id, duty_date.year, duty_date.month, month_assignments, staff_by_id, holidays, duty_weights
                ))
                for s in peers
            ),
            key=lambda pair: pair[1],
        )[:_MAX_SUGGESTIONS_PER_GROUP]
        if not weighted:
            continue
        any_suggestion = True
        st.caption(trinh_do)
        for s, weight in weighted:
            if st.button(
                f"+ {s.ho_va_ten} — {weight:g} điểm tháng {duty_date.month:02d}",
                key=f"suggest_{duty_date.isoformat()}_{s.bmo_id}",
                width="stretch",
            ):
                current = list(st.session_state.get(ms_key, []))
                if s.bmo_id not in current:
                    current.append(s.bmo_id)
                    st.session_state[ms_key] = current
                st.rerun(scope="fragment")
    if not any_suggestion:
        st.caption("Không có gợi ý (tất cả nhân viên phù hợp đã bận ngày này).")


@st.dialog("Phân công trực", width="medium")
def _assign_dialog(duty_date: date, base: str, staff_by_id: dict) -> None:
    state_key = f"assign_conflicts_{duty_date.isoformat()}_{base}"
    state: dict | None = st.session_state.get(state_key)
    other_base = _other_base(base)
    is_weekend_day = duty_date.weekday() in _WEEKEND_WEEKDAYS

    if state is None:
        st.write(f"Ngày: **{duty_date.strftime('%d/%m/%Y')}** — Cơ sở: **{BASE_SHORT_LABELS[base]}**")

        half_day = False
        if is_weekend_day:
            half_day = st.checkbox(
                "Trực nửa ngày (weekend_half — trọng số bằng 1/2 ngày trực đầy đủ)",
                key=f"half_day_{duty_date.isoformat()}_{base}",
            )

        ms_key = f"assign_select_{duty_date.isoformat()}_{base}"
        busy_ids = {
            row["staff_id"]
            for row in repository.get_assignments_with_ids_for_range(duty_date, duty_date)
        }
        with st.expander("💡 Gợi ý nhân viên có điểm trực thấp", expanded=True):
            _suggest_low_weight_staff(duty_date, staff_by_id, ms_key, busy_ids)

        active_staff = sorted((s for s in staff_by_id.values() if s.is_active), key=lambda s: s.ho_va_ten)
        options = {s.bmo_id: _staff_label(s) for s in active_staff}
        selected_ids = st.multiselect(
            "Nhân viên",
            options=list(options.keys()),
            format_func=lambda bmo_id: options[bmo_id],
            key=ms_key,
        )

        if st.button("Phân công", type="primary", disabled=not selected_ids):
            # A staff member can't work both bases the same day: assign
            # anyone free right away, and defer anyone already booked at
            # the other base to the confirmation step below.
            conflicts = []
            errors = []
            for bmo_id in selected_ids:
                existing = repository.find_assignment(duty_date, other_base, bmo_id)
                if existing:
                    conflicts.append({"assignment_id": existing["id"], "staff_id": bmo_id})
                else:
                    try:
                        repository.assign_staff(duty_date, base, bmo_id, is_half_day=half_day)
                    except DuplicateAssignmentError as exc:
                        errors.append(str(exc))
            if errors:
                st.error("\n".join(errors))
            if conflicts:
                st.session_state[state_key] = {"conflicts": conflicts, "is_half_day": half_day}
                st.rerun(scope="fragment")
            elif not errors:
                st.rerun()
    else:
        conflicts = state["conflicts"]
        half_day = state["is_half_day"]
        st.warning(
            f"Nhân viên sau đã được phân trực tại **{BASE_SHORT_LABELS[other_base]}** ngày "
            f"{duty_date.strftime('%d/%m/%Y')}. Chuyển sang **{BASE_SHORT_LABELS[base]}**?"
        )
        conflict = conflicts[0]
        staff = staff_by_id.get(conflict["staff_id"])
        st.write(f"**{staff.ho_va_ten if staff else conflict['staff_id']}**")

        col_yes, col_no = st.columns(2)
        with col_yes:
            move_clicked = st.button("Có, chuyển", key=f"move_yes_{conflict['assignment_id']}", type="primary", width="stretch")
        with col_no:
            keep_clicked = st.button("Không, giữ nguyên", key=f"move_no_{conflict['assignment_id']}", width="stretch")

        if move_clicked:
            try:
                repository.move_assignment(conflict["assignment_id"], base, is_half_day=half_day)
            except DuplicateAssignmentError as exc:
                st.error(str(exc))
                keep_clicked = False
                move_clicked = False  # keep this conflict pending so the user can retry

        if move_clicked or keep_clicked:
            remaining = conflicts[1:]
            if remaining:
                st.session_state[state_key] = {"conflicts": remaining, "is_half_day": half_day}
                st.rerun(scope="fragment")
            else:
                st.session_state.pop(state_key, None)
                st.rerun()


@st.dialog("Thông tin nhân viên")
def _info_dialog(
    assignment_id: int, staff_id: str, ref_year: int, ref_month: int, staff_by_id: dict, is_half_day: bool = False
) -> None:
    staff = staff_by_id.get(staff_id)
    if staff is None:
        st.error("Không tìm thấy thông tin nhân viên.")
        return

    st.markdown(f"### {staff.ho_va_ten}")
    if is_half_day:
        st.caption("🕐 Trực nửa ngày (weekend_half)")
    st.write(f"Mã nhân viên: {staff.bmo_id}")
    st.write(f"Giới tính: {staff.gioi_tinh or '-'}")
    st.write(f"Điện thoại: {staff.so_dien_thoai or '-'}")
    st.write(f"Trình độ: {staff.trinh_do or '-'}")
    st.write(f"Nhóm vị trí: {classify_position(staff.vi_tri)} ({staff.vi_tri})")
    if staff.mang_thai:
        st.warning("Đang mang thai")
    if staff.sinh_de:
        st.warning("Đang trong chế độ sau sinh")
    if staff.ghi_chu:
        st.caption(f"Ghi chú: {staff.ghi_chu}")

    st.divider()
    st.markdown("**Điểm trực tích lũy**")

    all_staff = list(staff_by_id.values())
    holidays = repository.get_all_holidays()
    duty_weights = repository.get_duty_weights()
    assignments = repository.get_assignments_for_months(ref_year, ref_month, N_TRAILING_MONTHS)

    monthly = compute_monthly_weights(
        staff_id, ref_year, ref_month, assignments, staff_by_id, holidays, duty_weights,
        n_trailing=N_TRAILING_MONTHS,
    )
    for month_key, total in monthly.items():
        st.write(f"{month_key}: **{total:g}** điểm")

    if staff.trinh_do:
        peer_avg = compute_peer_average(
            staff.trinh_do, ref_year, ref_month, all_staff, assignments, holidays, duty_weights,
        )
        my_total = monthly.get(f"{ref_year:04d}-{ref_month:02d}", 0.0)
        if peer_avg > 0:
            diff_pct = (my_total - peer_avg) / peer_avg * 100
            if abs(diff_pct) < 0.5:
                comparison = f"bằng trung bình nhóm '{staff.trinh_do}' ({peer_avg:.2f} điểm)"
            else:
                direction = "cao hơn" if diff_pct > 0 else "thấp hơn"
                comparison = f"{direction} {abs(diff_pct):.0f}% so với trung bình nhóm '{staff.trinh_do}' {peer_avg:.2f} điểm"
        else:
            comparison = f"Trung bình nhóm '{staff.trinh_do}' tháng {ref_month:02d}/{ref_year} là {peer_avg:.2f} điểm"
        st.caption(comparison[0].upper() + comparison[1:])

    if not is_view_only():
        st.divider()
        toggle_label = "Chuyển thành trực 24/24" if is_half_day else "Chuyển thành trực 12/24"
        if st.button(toggle_label):
            repository.set_half_day(assignment_id, not is_half_day)
            st.rerun()
        if st.button("Hủy phân công", type="secondary"):
            repository.unassign_staff(assignment_id)
            st.rerun()


@st.dialog("Xóa tất cả lịch trực")
def _confirm_delete_all_dialog() -> None:
    st.warning(
        "Hành động này sẽ xóa **toàn bộ** lịch phân trực đã có (tất cả các tháng, cả hai cơ sở), "
        "không thể hoàn tác. Bạn có chắc chắn muốn tiếp tục?"
    )
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Có, xóa tất cả", type="primary", width="stretch"):
            st.session_state["_deleted_all_count"] = repository.delete_all_assignments()
            st.rerun()
    with col_no:
        if st.button("Không, hủy", width="stretch"):
            st.rerun()


def _inject_styles(weeks: list[list[date]], holidays: list) -> None:
    """One consolidated <style> block: chip colors (explicit, matching the
    legend) + per-day background highlights (weekend/holiday, with today's
    tint layered on top at ~50% opacity so the base highlight still shows
    through)."""
    rules = [
        f"[class*='st-key-chip_dh_'] button {{ "
        f"background-color: {_DAI_HOC_BG} !important; color: {_DAI_HOC_TEXT} !important; "
        f"border-color: {_DAI_HOC_BG} !important; }}",
        f"[class*='st-key-chip_cd_'] button {{ "
        f"background-color: {_CAO_DANG_BG} !important; color: {_CAO_DANG_TEXT} !important; "
        f"border-color: {_CAO_DANG_BG} !important; }}",
    ]

    today = date.today()
    for week in weeks:
        for day in week:
            is_weekend = day.weekday() in _WEEKEND_WEEKDAYS
            is_holiday = resolve_holiday_name(day, holidays) is not None
            base_bg = _HOLIDAY_BG if is_holiday else (_WEEKEND_BG if is_weekend else None)

            declarations = []
            if base_bg:
                declarations.append(f"background-color: {base_bg};")
            if day == today:
                declarations.append(f"background-image: linear-gradient({_TODAY_OVERLAY}, {_TODAY_OVERLAY});")
            if declarations:
                rules.append(f".st-key-day_{day.isoformat()} {{ {' '.join(declarations)} }}")

    st.html(f"<style>{''.join(rules)}</style>")


def _render_day_cell(day: date, current_month: int, by_date_base: dict, staff_by_id: dict, holidays: list, ref_year: int, ref_month: int) -> None:
    in_month = day.month == current_month
    number_color = "inherit" if in_month else "#9CA3AF"
    holiday_name = resolve_holiday_name(day, holidays)

    header_html = f"<div style='text-align:center;font-size:1.4rem;font-weight:700;color:{number_color};line-height:1.1;'>{day.day}</div>"
    if holiday_name:
        header_html += (
            f"<div style='text-align:center;font-size:0.7rem;font-weight:600;color:#B91C1C;"
            f"line-height:1.2;margin-bottom:2px;'>{holiday_name}</div>"
        )

    with st.container(border=True, key=f"day_{day.isoformat()}"):
        st.html(header_html)
        sub_cols = st.columns(2, gap="small")
        for sub_col, base in zip(sub_cols, BASES):
            with sub_col:
                st.caption(BASE_SHORT_LABELS[base])
                entries = sorted(by_date_base.get((day, base), []), key=lambda e: _sort_key(e, staff_by_id))
                for entry in entries:
                    staff = staff_by_id.get(entry["staff_id"])
                    name = staff.ho_va_ten if staff else entry["staff_id"]
                    if entry.get("is_half_day"):
                        name = f"{name} (½)"
                    trinh_do = staff.trinh_do if staff else None
                    if st.button(
                        name, key=_chip_key(entry["id"], trinh_do), width="stretch", wrap=True
                    ):
                        _info_dialog(
                            entry["id"], entry["staff_id"], ref_year, ref_month, staff_by_id,
                            is_half_day=entry.get("is_half_day", False),
                        )
                if not is_view_only():
                    if st.button("+", key=f"add_{day.isoformat()}_{base}", width="stretch"):
                        _assign_dialog(day, base, staff_by_id)


def render() -> None:
    if "_deleted_all_count" in st.session_state:
        st.success(f"Đã xóa {st.session_state.pop('_deleted_all_count')} lượt phân trực.")

    today = date.today()
    st.session_state.setdefault("cal_year", today.year)
    st.session_state.setdefault("cal_month", today.month)
    year = st.session_state["cal_year"]
    month = st.session_state["cal_month"]

    col_prev, col_today, col_next, col_title = st.columns([1, 1, 1, 5])
    with col_prev:
        if st.button(":material/chevron_left:", key="cal_prev", width="stretch"):
            st.session_state["cal_year"], st.session_state["cal_month"] = _shift_month(year, month, -1)
            st.rerun()
    with col_today:
        if st.button("Hôm nay", key="cal_today", width="stretch"):
            st.session_state["cal_year"], st.session_state["cal_month"] = today.year, today.month
            st.rerun()
    with col_next:
        if st.button(":material/chevron_right:", key="cal_next", width="stretch"):
            st.session_state["cal_year"], st.session_state["cal_month"] = _shift_month(year, month, 1)
            st.rerun()
    with col_title:
        st.subheader(f"Tháng {month:02d}/{year}")

    st.html(
        "<div style='display:flex;gap:20px;align-items:center;font-size:0.85rem;margin-bottom:8px;'>"
        f"<span><span style='display:inline-block;width:12px;height:12px;background:{_DAI_HOC_BG};"
        "border-radius:3px;margin-right:5px;vertical-align:middle;'></span>Đại học</span>"
        f"<span><span style='display:inline-block;width:12px;height:12px;background:{_CAO_DANG_BG};"
        f"border:1px solid {_DAI_HOC_BG};border-radius:3px;margin-right:5px;vertical-align:middle;'></span>Cao đẳng</span>"
        f"<span><span style='display:inline-block;width:12px;height:12px;background:{_HOLIDAY_BG};"
        "border-radius:3px;margin-right:5px;vertical-align:middle;'></span>Ngày lễ</span>"
        f"<span><span style='display:inline-block;width:12px;height:12px;background:{_WEEKEND_BG};"
        "border-radius:3px;margin-right:5px;vertical-align:middle;'></span>Cuối tuần</span>"
        "<span style='color:#6b7280;'>Bấm tên để xem thông tin · bấm + để phân công</span>"
        "</div>"
    )

    if not is_view_only():
        col_spacer, col_delete_all = st.columns([6, 1])
        with col_delete_all:
            if st.button(":material/delete_forever: Xóa tất cả lịch trực", key="cal_delete_all", width="stretch"):
                _confirm_delete_all_dialog()

    weeks = calendar_module.Calendar(firstweekday=0).monthdatescalendar(year, month)
    grid_start, grid_end = weeks[0][0], weeks[-1][-1]

    staff_by_id = repository.get_all_staff_by_id()
    holidays = repository.get_all_holidays()
    _inject_styles(weeks, holidays)

    rows = repository.get_assignments_with_ids_for_range(grid_start, grid_end)
    by_date_base = defaultdict(list)
    for row in rows:
        by_date_base[(row["duty_date"], row["base"])].append(row)

    header_cols = st.columns(7)
    for col, label in zip(header_cols, _WEEKDAY_LABELS):
        col.markdown(f"**{label}**")

    for week in weeks:
        row_cols = st.columns(7)
        for col, day in zip(row_cols, week):
            with col:
                _render_day_cell(day, month, by_date_base, staff_by_id, holidays, year, month)
