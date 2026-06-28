"""Session state helpers."""

from __future__ import annotations

import streamlit as st


def init_state() -> None:
    st.session_state.setdefault("app_ready", True)
