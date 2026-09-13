"""Shared "download template / upload data" widget pair for the Data tab's
spreadsheet editors."""

from __future__ import annotations

import io
from typing import Callable

import pandas as pd
import streamlit as st

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _make_template_bytes(columns: list[str], sample_row: dict | None) -> bytes:
    df = pd.DataFrame([sample_row] if sample_row else [], columns=columns)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


def render_template_download_and_upload(
    *,
    template_filename: str,
    columns: list[str],
    sample_row: dict | None,
    importer: Callable[[pd.DataFrame], int],
    key_prefix: str,
) -> None:
    """Renders a "download template" button next to a "upload xlsx" flow.
    `importer` is called with the parsed DataFrame and must return the
    number of rows imported; it should be additive (upsert-only, no
    deletion of existing rows not present in the file)."""
    col_download, col_upload = st.columns([1, 2])
    with col_download:
        st.download_button(
            "Tải file mẫu",
            data=_make_template_bytes(columns, sample_row),
            file_name=template_filename,
            mime=_XLSX_MIME,
            key=f"{key_prefix}_download_template",
        )
    with col_upload:
        uploaded = st.file_uploader(
            "Tải lên file Excel để nhập dữ liệu",
            type=["xlsx"],
            key=f"{key_prefix}_uploader",
            label_visibility="collapsed",
        )
        if uploaded is not None:
            if st.button("Nhập dữ liệu từ file", key=f"{key_prefix}_import_btn"):
                df = pd.read_excel(uploaded)
                missing = set(columns) - set(df.columns)
                if missing:
                    st.error(f"File thiếu cột: {', '.join(sorted(missing))}")
                else:
                    count = importer(df)
                    st.success(f"Đã nhập {count} dòng từ file.")
                    st.rerun()
