"""Outputs tab: disabled stub for the future .docx roster-generation module.

Extension point: once built, this module will read finished schedules via
`app.repository.get_assignments_for_range()` and render them into the
pre-defined .docx formats currently kept under archives/.
"""

from __future__ import annotations

import streamlit as st


def render() -> None:
    st.info("Chức năng xuất file (.docx) sẽ được xây dựng ở giai đoạn sau.")
