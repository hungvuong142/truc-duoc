"""Calendar tab, built from native Streamlit layout (not the
streamlit-calendar component), in two views:

- weekly_view ("Chế độ xem theo ngày", the default): the month as a scrolling
  list of day rows. Each row shows both bases side by side -- CSHN then CSNB,
  each with a DS Đại học and a DS Cao đẳng column (like the Word roster) --
  under a frozen header.
- monthly_view ("Chế độ xem theo tháng"): the classic 7-column month grid,
  each day cell split into CSHN | CSNB.

Both show 24/24 staff above 12/24, colored by trình độ, with click-to-view
contact info.

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
import streamlit.components.v1 as components

from app import repository
from app.config import BASE_SHORT_LABELS, BASES, N_TRAILING_MONTHS, NHA_THUOC_KEYWORD, WEEKDAY_LABELS
from app.logic.calendar_rules import classify_position, resolve_holiday_name
from app.logic.weights import compute_monthly_weights, compute_peer_average, compute_single_month_weight
from app.repository import DuplicateAssignmentError
from app.ui import assignment_xlsx
from app.ui.access import is_view_only

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

# Chip text is 20% smaller than the default 1rem so long names wrap less in
# the narrow half-cell (CSHN/CSNB share one day column).
_CHIP_FONT_SIZE = "1rem"

# Config here -- where the "+" (assign) button sits under its base's chips:
# "left", "center" or "right" of the whole CSHN/CSNB block. A content-width
# button's container is a flex item of the block's vertical stack, so
# _inject_styles turns this into an `align-self` (the cross axis, i.e.
# horizontal) rule on that container.
_ADD_BUTTON_ALIGN = "center"
_ALIGN_TO_FLEX = {"left": "flex-start", "center": "center", "right": "flex-end"}

_VIEW_WEEKLY = "weekly_view"
_VIEW_MONTHLY = "monthly_view"
_VIEW_LABELS = {_VIEW_WEEKLY: "Chế độ xem theo ngày", _VIEW_MONTHLY: "Chế độ xem theo tháng"}

# Config here -- when "Hôm nay" scrolls today's row into view, leave this much
# room above it so it isn't hidden behind Streamlit's toolbar (and, in the
# weekly view, the frozen column header).
_WEEKLY_SCROLL_MARGIN = "8rem"
_MONTHLY_SCROLL_MARGIN = "4.5rem"

# Config here -- gap between the top of the scroll area and the frozen column
# header: Streamlit's own fixed toolbar is 3.75rem tall.
_STICKY_HEADER_TOP = "3.75rem"

# Text color for a chip whose staff is mang_thai/sinh_de, despite still
# being assigned (the assign dialog warns but lets the user proceed).
_FLAGGED_TEXT = "#DC2626"


def _staff_label(staff) -> str:
    if classify_position(staff.vi_tri) != "Nội trú":
        return f"{staff.ho_va_ten} ({staff.trinh_do or '?'}) ({staff.vi_tri})"
    return f"{staff.ho_va_ten} ({staff.bmo_id}) · {staff.trinh_do or '?'}"


def _chip_name(staff) -> str:
    """"NGUYỄN THỊ THU · K1": name upper-cased, then a short vi_tri only for
    Nhà thuốc staff ("Nhà thuốc K1" -> "K1"); Nội trú -- the majority -- gets
    no suffix, which keeps the chip short in the narrow half-cell."""
    name = staff.ho_va_ten.upper()
    if classify_position(staff.vi_tri) == "Nội trú":
        return name
    short = staff.vi_tri.replace(NHA_THUOC_KEYWORD, "").strip()
    return f"{name} · {short or NHA_THUOC_KEYWORD}"


def _chip_tooltip(staff) -> str:
    """Full "NAME (vi_tri)" shown on hover."""
    name = staff.ho_va_ten.upper()
    return f"{name} ({staff.vi_tri})" if staff.vi_tri else name


def _is_dai_hoc_entry(entry: dict, staff_by_id: dict) -> bool:
    """Which roster column an assignment belongs to: a DSĐH covering a Cao
    đẳng slot counts as Cao đẳng, and so does anyone without a recognised
    trinh_do."""
    staff = staff_by_id.get(entry["staff_id"])
    return bool(staff and staff.trinh_do == "Đại học" and not entry.get("is_cao_dang_cover"))


def _sort_key(entry: dict, staff_by_id: dict) -> tuple:
    staff = staff_by_id.get(entry["staff_id"])
    trinh_do_rank = 0 if _is_dai_hoc_entry(entry, staff_by_id) else 1
    half_day_rank = 1 if entry.get("is_half_day") else 0
    name = staff.ho_va_ten if staff else entry["staff_id"]
    return (trinh_do_rank, half_day_rank, name)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    zero_based = (year * 12 + (month - 1)) + delta
    return zero_based // 12, zero_based % 12 + 1


def _chip_key(
    entry_id: int, trinh_do: str | None, flagged: bool = False, cao_dang_cover: bool = False
) -> str:
    if cao_dang_cover:
        bucket = "cover"
    else:
        bucket = "dh" if trinh_do == "Đại học" else "cd"
    suffix = "_flag" if flagged else ""
    return f"chip_{bucket}_{entry_id}{suffix}"


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
    ninh_binh_months = repository.get_ninh_binh_assignment_months()
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
                    s.bmo_id, duty_date.year, duty_date.month, month_assignments, holidays,
                    duty_weights, ninh_binh_months,
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

    def _attempt_assign(ids: list[str], half_day: bool, cao_dang_cover: bool) -> None:
        # A staff member can't work both bases the same day: assign anyone
        # free right away, and defer anyone already booked at the other
        # base to the move-conflict confirmation stage below.
        conflicts = []
        errors = []
        for bmo_id in ids:
            existing = repository.find_assignment(duty_date, other_base, bmo_id)
            if existing:
                conflicts.append({"assignment_id": existing["id"], "staff_id": bmo_id})
            else:
                try:
                    repository.assign_staff(
                        duty_date, base, bmo_id, is_half_day=half_day, is_cao_dang_cover=cao_dang_cover
                    )
                except DuplicateAssignmentError as exc:
                    errors.append(str(exc))
        if errors:
            st.error("\n".join(errors))
        if conflicts:
            st.session_state[state_key] = {
                "stage": "conflicts", "conflicts": conflicts,
                "is_half_day": half_day, "cao_dang_cover": cao_dang_cover,
            }
            st.rerun(scope="fragment")
        elif not errors:
            st.rerun()

    if state is None:
        st.write(f"Ngày: **{duty_date.strftime('%d/%m/%Y')}** — Cơ sở: **{BASE_SHORT_LABELS[base]}**")

        half_day = st.checkbox(
            "Trực nửa ngày (half_day — trọng số bằng 1/2 ngày trực đầy đủ)",
            key=f"half_day_{duty_date.isoformat()}_{base}",
        )
        cao_dang_cover = st.checkbox(
            "DSĐH trực vị trí cao đẳng",
            key=f"cao_dang_cover_{duty_date.isoformat()}_{base}",
            help=(
                "Dược sĩ đại học trực thay vị trí cao đẳng: tính vào thống kê nhóm "
                "Cao đẳng thay vì Đại học cho lượt trực này, không đổi trình độ của nhân viên."
            ),
        )

        ms_key = f"assign_select_{duty_date.isoformat()}_{base}"
        # Off by default and computed only when switched on: the suggestion
        # list costs a few queries per dialog open, and most assignments
        # don't need it.
        if st.toggle("💡 Gợi ý nhân viên có điểm trực thấp", key=f"show_suggest_{duty_date.isoformat()}_{base}"):
            busy_ids = {
                row["staff_id"]
                for row in repository.get_assignments_with_ids_for_range(duty_date, duty_date)
            }
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
            flagged_ids = [
                bmo_id for bmo_id in selected_ids
                if (s := staff_by_id.get(bmo_id)) and (s.mang_thai or s.sinh_de)
            ]
            if flagged_ids:
                st.session_state[state_key] = {
                    "stage": "confirm_flagged",
                    "queue": flagged_ids,
                    "accepted_ids": [bmo_id for bmo_id in selected_ids if bmo_id not in flagged_ids],
                    "is_half_day": half_day,
                    "cao_dang_cover": cao_dang_cover,
                }
                st.rerun(scope="fragment")
            else:
                _attempt_assign(selected_ids, half_day, cao_dang_cover)

    elif state["stage"] == "confirm_flagged":
        queue = state["queue"]
        half_day = state["is_half_day"]
        cao_dang_cover = state["cao_dang_cover"]
        current_id = queue[0]
        staff = staff_by_id.get(current_id)
        name = staff.ho_va_ten if staff else current_id
        st.warning(f"Bạn có muốn phân lịch trực vào nhân viên **{name}** hiện đang mang thai/sinh đẻ?")

        col_yes, col_no = st.columns(2)
        with col_yes:
            yes_clicked = st.button(
                "Có", key=f"preg_yes_{duty_date.isoformat()}_{base}_{current_id}", type="primary", width="stretch"
            )
        with col_no:
            no_clicked = st.button(
                "Không", key=f"preg_no_{duty_date.isoformat()}_{base}_{current_id}", width="stretch"
            )

        if yes_clicked or no_clicked:
            accepted_ids = state["accepted_ids"] + ([current_id] if yes_clicked else [])
            remaining = queue[1:]
            if remaining:
                st.session_state[state_key] = {
                    "stage": "confirm_flagged", "queue": remaining,
                    "accepted_ids": accepted_ids, "is_half_day": half_day, "cao_dang_cover": cao_dang_cover,
                }
                st.rerun(scope="fragment")
            else:
                st.session_state.pop(state_key, None)
                if accepted_ids:
                    _attempt_assign(accepted_ids, half_day, cao_dang_cover)
                else:
                    st.rerun()

    else:  # state["stage"] == "conflicts"
        conflicts = state["conflicts"]
        half_day = state["is_half_day"]
        cao_dang_cover = state["cao_dang_cover"]
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
                repository.move_assignment(
                    conflict["assignment_id"], base, is_half_day=half_day, is_cao_dang_cover=cao_dang_cover
                )
            except DuplicateAssignmentError as exc:
                st.error(str(exc))
                keep_clicked = False
                move_clicked = False  # keep this conflict pending so the user can retry

        if move_clicked or keep_clicked:
            remaining = conflicts[1:]
            if remaining:
                st.session_state[state_key] = {
                    "stage": "conflicts", "conflicts": remaining,
                    "is_half_day": half_day, "cao_dang_cover": cao_dang_cover,
                }
                st.rerun(scope="fragment")
            else:
                st.session_state.pop(state_key, None)
                st.rerun()


@st.dialog("Thông tin nhân viên")
def _info_dialog(
    assignment_id: int, staff_id: str, ref_year: int, ref_month: int, staff_by_id: dict,
    is_half_day: bool = False, is_cao_dang_cover: bool = False,
) -> None:
    staff = staff_by_id.get(staff_id)
    if staff is None:
        st.error("Không tìm thấy thông tin nhân viên.")
        return

    st.markdown(f"### {staff.ho_va_ten}")
    if is_half_day:
        st.caption("🕐 Trực nửa ngày (half_day)")
    if is_cao_dang_cover:
        st.caption("🎓 DSĐH trực vị trí cao đẳng (tính vào thống kê nhóm Cao đẳng)")
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
    ninh_binh_months = repository.get_ninh_binh_assignment_months()
    assignments = repository.get_assignments_for_months(ref_year, ref_month, N_TRAILING_MONTHS)

    monthly = compute_monthly_weights(
        staff_id, ref_year, ref_month, assignments, holidays, duty_weights,
        n_trailing=N_TRAILING_MONTHS, ninh_binh_months=ninh_binh_months,
    )
    for month_key, total in monthly.items():
        year_part, month_part = month_key.split("-")  # keys are "YYYY-MM"; shown as MM/YYYY
        st.write(f"{month_part}/{year_part}: **{total:g}** điểm")

    # A DSĐH-covering-Cao-đẳng assignment in the reference month reclassifies
    # this staff into the Cao đẳng peer group for that month's comparison
    # only -- staff.trinh_do (shown above) and every other month are
    # unaffected.
    effective_trinh_do = staff.trinh_do
    if any(
        a.staff_id == staff_id and a.duty_date.year == ref_year and a.duty_date.month == ref_month
        and a.is_cao_dang_cover
        for a in assignments
    ):
        effective_trinh_do = "Cao đẳng"

    if effective_trinh_do:
        peer_avg = compute_peer_average(
            effective_trinh_do, ref_year, ref_month, all_staff, assignments, holidays, duty_weights,
            ninh_binh_months,
        )
        my_total = monthly.get(f"{ref_year:04d}-{ref_month:02d}", 0.0)
        if peer_avg > 0:
            diff_pct = (my_total - peer_avg) / peer_avg * 100
            if abs(diff_pct) < 0.5:
                comparison = f"bằng trung bình nhóm '{effective_trinh_do}' ({peer_avg:.2f} điểm)"
            else:
                direction = "cao hơn" if diff_pct > 0 else "thấp hơn"
                comparison = (
                    f"{direction} {abs(diff_pct):.0f}% so với trung bình nhóm "
                    f"'{effective_trinh_do}' {peer_avg:.2f} điểm"
                )
        else:
            comparison = f"Trung bình nhóm '{effective_trinh_do}' tháng {ref_month:02d}/{ref_year} là {peer_avg:.2f} điểm"
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


@st.dialog("Xóa lịch trực theo tháng")
def _confirm_delete_month_dialog(year: int, month: int) -> None:
    st.warning(
        f"Hành động này sẽ xóa **toàn bộ** lịch phân trực của **tháng {month:02d}/{year}** "
        "(cả hai cơ sở), không thể hoàn tác. Lịch của các tháng khác được giữ nguyên. "
        "Bạn có chắc chắn muốn tiếp tục?"
    )
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Có, xóa tháng này", type="primary", width="stretch"):
            count = repository.delete_assignments_in_month(year, month)
            st.session_state["_cal_flash"] = f"Đã xóa {count} lượt phân trực của tháng {month:02d}/{year}."
            st.rerun()
    with col_no:
        if st.button("Không, hủy", width="stretch"):
            st.rerun()


def _page_background() -> str:
    """The frozen header needs an opaque fill (rows scroll underneath it), and
    Streamlit exposes no CSS variable for the page background -- so use the
    configured theme color, else the built-in light/dark default."""
    configured = st.get_option("theme.backgroundColor")
    if configured:
        return configured
    return "#0E1117" if st.context.theme.get("type") == "dark" else "#FFFFFF"


def _inject_styles(days: list[date], holidays: list, scroll_margin: str) -> None:
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
        f"[class*='st-key-chip_cover_'] button {{ "
        f"background-color: #FFFFFF !important; color: {_DAI_HOC_BG} !important; "
        f"border-color: {_DAI_HOC_BG} !important; }}",
        f"[class*='st-key-chip_'] button p {{ font-size: {_CHIP_FONT_SIZE} !important; }}",
        "[class*='st-key-chip_'] button { min-height: 2rem !important; padding: 0.15rem 0.5rem !important; }",
        f"[class*='st-key-add_'] {{ align-self: {_ALIGN_TO_FLEX[_ADD_BUTTON_ALIGN]}; }}",
        # A keyed container is wrapped in a stLayoutWrapper sized to itself,
        # so it is the wrapper (a child of the page-long block) that must be
        # sticky -- position: sticky only travels inside its parent.
        f"[data-testid='stLayoutWrapper']:has(> .st-key-cal_header) {{ position: sticky; "
        f"top: {_STICKY_HEADER_TOP}; z-index: 50; background-color: {_page_background()}; }}",
        ".st-key-cal_header [data-testid='stMarkdownContainer'] { text-align: center; }",
        f"[class*='st-key-chip_'][class*='_flag'] button {{ "
        f"color: {_FLAGGED_TEXT} !important; font-weight: 700; }}",
    ]

    today = date.today()
    for day in days:
        is_weekend = day.weekday() in _WEEKEND_WEEKDAYS
        is_holiday = resolve_holiday_name(day, holidays) is not None
        base_bg = _HOLIDAY_BG if is_holiday else (_WEEKEND_BG if is_weekend else None)

        declarations = []
        if base_bg:
            declarations.append(f"background-color: {base_bg};")
        if day == today:
            declarations.append(f"background-image: linear-gradient({_TODAY_OVERLAY}, {_TODAY_OVERLAY});")
            declarations.append(f"scroll-margin-top: {scroll_margin};")
        if declarations:
            rules.append(f".st-key-day_{day.isoformat()} {{ {' '.join(declarations)} }}")

    st.html(f"<style>{''.join(rules)}</style>")


def _render_chip(entry: dict, staff_by_id: dict, ref_year: int, ref_month: int) -> None:
    staff = staff_by_id.get(entry["staff_id"])
    name = _chip_name(staff) if staff else entry["staff_id"]
    if entry.get("is_half_day"):
        name = f"{name} (½)"
    trinh_do = staff.trinh_do if staff else None
    flagged = bool(staff and (staff.mang_thai or staff.sinh_de))
    cao_dang_cover = bool(entry.get("is_cao_dang_cover"))
    if st.button(
        name, key=_chip_key(entry["id"], trinh_do, flagged, cao_dang_cover), width="stretch", wrap=True,
        help=_chip_tooltip(staff) if staff else None,
    ):
        _info_dialog(
            entry["id"], entry["staff_id"], ref_year, ref_month, staff_by_id,
            is_half_day=entry.get("is_half_day", False), is_cao_dang_cover=cao_dang_cover,
        )


# Ngày/Thứ, then one block per base (CSHN, CSNB); each block is split into
# DS Đại học | DS Cao đẳng, with the "+" button under them.
_ROW_COLUMNS = [1.2] + [8] * len(BASES)
_SUB_COLUMNS = [1, 1]


def _render_chips_split_by_shift(entries: list[dict], staff_by_id: dict, ref_year: int, ref_month: int) -> None:
    """24/24 chips, a dashed divider, then 12/24 chips (divider only when both
    exist). `entries` are already sorted."""
    full_day = [e for e in entries if not e.get("is_half_day")]
    half_day = [e for e in entries if e.get("is_half_day")]
    for entry in full_day:
        _render_chip(entry, staff_by_id, ref_year, ref_month)
    if full_day and half_day:
        st.html("<hr style='margin:4px 0;border:none;border-top:1px dashed #9CA3AF;'>")
    for entry in half_day:
        _render_chip(entry, staff_by_id, ref_year, ref_month)


def _render_day_row(
    day: date, by_date_base: dict, staff_by_id: dict, holidays: list, ref_year: int, ref_month: int
) -> None:
    holiday_name = resolve_holiday_name(day, holidays)
    date_html = (
        f"<div style='text-align:center;line-height:1.15;'>"
        f"<div style='font-size:1.4rem;font-weight:700;'>{day.day}</div>"
        f"<div style='font-size:0.85rem;opacity:0.7;'>{WEEKDAY_LABELS[day.weekday()]}</div>"
    )
    if holiday_name:
        date_html += f"<div style='font-size:0.7rem;font-weight:600;color:#B91C1C;'>{holiday_name}</div>"
    date_html += "</div>"

    with st.container(border=True, key=f"day_{day.isoformat()}"):
        cols = st.columns(_ROW_COLUMNS, gap="small")
        with cols[0]:
            st.html(date_html)
        for col, base in zip(cols[1:], BASES):
            entries = sorted(by_date_base.get((day, base), []), key=lambda e: _sort_key(e, staff_by_id))
            with col:
                col_dai_hoc, col_cao_dang = st.columns(_SUB_COLUMNS, gap="small")
                with col_dai_hoc:
                    _render_chips_split_by_shift(
                        [e for e in entries if _is_dai_hoc_entry(e, staff_by_id)], staff_by_id, ref_year, ref_month
                    )
                with col_cao_dang:
                    _render_chips_split_by_shift(
                        [e for e in entries if not _is_dai_hoc_entry(e, staff_by_id)], staff_by_id, ref_year, ref_month
                    )
                if not is_view_only():
                    if st.button("+", key=f"add_{day.isoformat()}_{base}", width="content"):
                        _assign_dialog(day, base, staff_by_id)


def _render_month_cell(
    day: date, current_month: int, by_date_base: dict, staff_by_id: dict, holidays: list,
    ref_year: int, ref_month: int,
) -> None:
    number_color = "inherit" if day.month == current_month else "#9CA3AF"
    holiday_name = resolve_holiday_name(day, holidays)
    # half_day duty (see resolve_assignment_weight) only ever applies on a
    # weekend or a holiday, so only those cells need the 24/24 vs 12/24
    # split -- a plain weekday cell keeps its single flat list.
    allows_half_day = day.weekday() in _WEEKEND_WEEKDAYS or holiday_name is not None

    header_html = (
        f"<div style='text-align:center;font-size:1.4rem;font-weight:700;color:{number_color};"
        f"line-height:1.1;'>{day.day}</div>"
    )
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
                if allows_half_day:
                    _render_chips_split_by_shift(entries, staff_by_id, ref_year, ref_month)
                else:
                    for entry in entries:
                        _render_chip(entry, staff_by_id, ref_year, ref_month)
                if not is_view_only():
                    if st.button("+", key=f"add_{day.isoformat()}_{base}", width="stretch"):
                        _assign_dialog(day, base, staff_by_id)


def _group_by_date_base(rows: list[dict]) -> dict:
    by_date_base = defaultdict(list)
    for row in rows:
        by_date_base[(row["duty_date"], row["base"])].append(row)
    return by_date_base


def _render_weekly_view(year: int, month: int, staff_by_id: dict, holidays: list) -> None:
    days = [date(year, month, d) for d in range(1, calendar_module.monthrange(year, month)[1] + 1)]
    _inject_styles(days, holidays, _WEEKLY_SCROLL_MARGIN)
    by_date_base = _group_by_date_base(repository.get_assignments_with_ids_for_range(days[0], days[-1]))

    # Same bordered-container structure as the day rows so the labels line up
    # with their columns; _inject_styles makes it stick to the top while the
    # month scrolls.
    with st.container(border=True, key="cal_header"):
        header_cols = st.columns(_ROW_COLUMNS, gap="small")
        header_cols[0].markdown("**Ngày**")
        for col, base in zip(header_cols[1:], BASES):
            with col:
                sub_dai_hoc, sub_cao_dang = st.columns(_SUB_COLUMNS, gap="small")
                sub_dai_hoc.markdown(f"**{BASE_SHORT_LABELS[base]} · Đại học**")
                sub_cao_dang.markdown(f"**{BASE_SHORT_LABELS[base]} · Cao đẳng**")

    for day in days:
        _render_day_row(day, by_date_base, staff_by_id, holidays, year, month)


def _render_monthly_view(year: int, month: int, staff_by_id: dict, holidays: list) -> None:
    weeks = calendar_module.Calendar(firstweekday=0).monthdatescalendar(year, month)
    days = [day for week in weeks for day in week]
    _inject_styles(days, holidays, _MONTHLY_SCROLL_MARGIN)
    by_date_base = _group_by_date_base(repository.get_assignments_with_ids_for_range(days[0], days[-1]))

    for col, label in zip(st.columns(7), WEEKDAY_LABELS):
        col.markdown(f"**{label}**")
    for week in weeks:
        for col, day in zip(st.columns(7), week):
            with col:
                _render_month_cell(day, month, by_date_base, staff_by_id, holidays, year, month)


def _scroll_to_today_script(today: date) -> str:
    """Runs once, right after the rows are rendered. It lives in a zero-height
    component iframe (an st.html <script> is not executed here) and reaches the
    app through window.parent; the row may not be in the DOM yet when the
    iframe loads, hence the retries."""
    return (
        "<script>(function(){var tries=0;var go=function(){"
        f"var el=window.parent.document.querySelector('.st-key-day_{today.isoformat()}');"
        "if(el){el.scrollIntoView({block:'start',behavior:'smooth'});}"
        "else if(tries++<30){setTimeout(go,100);}};go();})();</script>"
    )


def render() -> None:
    if "_cal_flash" in st.session_state:
        st.success(st.session_state.pop("_cal_flash"))

    today = date.today()
    st.session_state.setdefault("cal_year", today.year)
    st.session_state.setdefault("cal_month", today.month)
    year = st.session_state["cal_year"]
    month = st.session_state["cal_month"]

    col_prev, col_today, col_next, col_title, col_view = st.columns([1, 1, 1, 3, 3])
    # Created before the nav buttons on purpose: they call st.rerun(), and a
    # widget not yet created in an interrupted run loses its state -- the
    # view would snap back to weekly on every "Hôm nay"/prev/next click.
    with col_view:
        view = st.radio(
            "Chế độ xem", [_VIEW_WEEKLY, _VIEW_MONTHLY], format_func=_VIEW_LABELS.get,
            horizontal=True, key="cal_view", label_visibility="collapsed",
        )
    with col_prev:
        if st.button(":material/chevron_left:", key="cal_prev", width="stretch"):
            st.session_state["cal_year"], st.session_state["cal_month"] = _shift_month(year, month, -1)
            st.rerun()
    with col_today:
        if st.button("Hôm nay", key="cal_today", width="stretch"):
            st.session_state["cal_year"], st.session_state["cal_month"] = today.year, today.month
            st.session_state["_scroll_to_today"] = True
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
        col_spacer, col_delete_month = st.columns([4, 1])
        with col_delete_month:
            if st.button(
                f":material/delete_forever: Xóa lịch tháng {month:02d}/{year}",
                key="cal_delete_month", width="stretch",
            ):
                _confirm_delete_month_dialog(year, month)

    assignment_xlsx.render(year, month)

    staff_by_id = repository.get_all_staff_by_id()
    holidays = repository.get_all_holidays()
    if view == _VIEW_MONTHLY:
        _render_monthly_view(year, month, staff_by_id, holidays)
    else:
        _render_weekly_view(year, month, staff_by_id, holidays)

    if st.session_state.pop("_scroll_to_today", False):
        components.html(_scroll_to_today_script(today), height=0)
