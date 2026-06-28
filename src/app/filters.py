"""Reusable Streamlit filters."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.app.config import DEFAULT_END_YEAR, DEFAULT_START_YEAR


def year_range_filter(df: pd.DataFrame, key: str = "year_range") -> tuple[int, int]:
    years = sorted(int(year) for year in df["ano"].dropna().unique()) if "ano" in df else [DEFAULT_START_YEAR, DEFAULT_END_YEAR]
    min_year = max(min(years), DEFAULT_START_YEAR)
    max_year = min(max(years), DEFAULT_END_YEAR)
    return st.sidebar.slider("Intervalo de anos", min_year, max_year, (min_year, max_year), key=key)


def class_filter(df: pd.DataFrame, key: str = "classes") -> list[str]:
    column = "dsc_classe_consumo_mercado"
    classes = sorted(str(value) for value in df[column].dropna().unique()) if column in df else []
    return st.sidebar.multiselect("Classes de consumo", classes, default=classes, key=key)


def distributor_filter(df: pd.DataFrame, include_all: bool = True, key: str = "distributor") -> str:
    column = "nom_agente_distribuidora"
    values = sorted(str(value) for value in df[column].dropna().unique()) if column in df else []
    options = ["Todas"] + values if include_all else values
    return st.sidebar.selectbox("Distribuidora", options, key=key) if options else "Todas"


def single_year_filter(df: pd.DataFrame, key: str = "single_year") -> int:
    years = sorted(int(year) for year in df["ano"].dropna().unique() if int(year) <= DEFAULT_END_YEAR)
    return st.sidebar.selectbox("Ano", years, index=len(years) - 1, key=key)


def moving_average_filter(key: str = "moving_average") -> bool:
    return st.sidebar.toggle("Média móvel de 3 meses", value=False, key=key)


def comparison_years_filter(key: str = "comparison_years") -> list[int]:
    options = list(range(DEFAULT_START_YEAR, DEFAULT_END_YEAR + 1))
    return st.sidebar.multiselect("Anos de comparação", options, default=[2019, 2020, 2021], key=key)


def apply_common_filters(df: pd.DataFrame, years: tuple[int, int], classes: list[str], distributor: str | None = None) -> pd.DataFrame:
    filtered = df[(df["ano"] >= years[0]) & (df["ano"] <= years[1])]
    if classes:
        filtered = filtered[filtered["dsc_classe_consumo_mercado"].isin(classes)]
    if distributor and distributor != "Todas" and "nom_agente_distribuidora" in filtered:
        filtered = filtered[filtered["nom_agente_distribuidora"] == distributor]
    return filtered
