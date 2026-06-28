"""Shared Streamlit layout helpers."""

from __future__ import annotations

import streamlit as st

from src.app.config import APP_SUBTITLE, APP_TITLE, DEFAULT_END_YEAR, DEFAULT_START_YEAR, MEASURE_NOTICE


def setup_page(page_title: str) -> None:
    st.set_page_config(page_title=f"{page_title} | {APP_TITLE}", page_icon=":zap:", layout="wide")


def render_header(title: str, description: str) -> None:
    st.title(title)
    st.caption(APP_SUBTITLE)
    st.write(description)
    st.info(f"Escopo padrão: {DEFAULT_START_YEAR}-{DEFAULT_END_YEAR}. {MEASURE_NOTICE}")


def render_sidebar_context() -> None:
    st.sidebar.header("Filtros")
    st.sidebar.caption("2026 fica fora do escopo padrão por poder estar parcial.")
