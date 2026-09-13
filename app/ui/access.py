"""View-only access mode: share a link with `?role=view` so staff can look
at the schedule/data without being able to edit it. This is a simple URL
switch, not real access control -- anyone can drop the query param and get
the normal editable app back. Fine for a trusted internal tool for now; a
real login (st.login) would be the next step if that ever matters.
"""

from __future__ import annotations

import streamlit as st


def is_view_only() -> bool:
    return st.query_params.get("role") == "view"
