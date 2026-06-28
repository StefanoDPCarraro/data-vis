"""Plotly chart builders for the Streamlit MVP."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.viz.annotations import add_historical_markers
from src.viz.theme import apply_default_layout, color_map


def empty_figure(message: str):
    fig = go.Figure()
    fig.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return apply_default_layout(fig)


def annual_consumption_line(df: pd.DataFrame):
    if df.empty:
        return empty_figure("Nenhum dado encontrado para os filtros selecionados.")
    annual = df.groupby("ano", as_index=False)["consumo_mwh"].sum()
    fig = px.line(
        annual,
        x="ano",
        y="consumo_mwh",
        markers=True,
        labels={"ano": "Ano", "consumo_mwh": "Consumo (MWh)"},
        hover_data={"consumo_mwh": ":,.1f"},
    )
    return apply_default_layout(fig)


def class_share_bar(df: pd.DataFrame):
    if df.empty:
        return empty_figure("Nenhum dado encontrado para os filtros selecionados.")
    grouped = df.groupby("dsc_classe_consumo_mercado", as_index=False)["consumo_mwh"].sum()
    grouped["participacao"] = grouped["consumo_mwh"] / grouped["consumo_mwh"].sum() * 100
    classes = grouped["dsc_classe_consumo_mercado"].tolist()
    fig = px.bar(
        grouped.sort_values("participacao", ascending=False),
        x="dsc_classe_consumo_mercado",
        y="participacao",
        color="dsc_classe_consumo_mercado",
        color_discrete_map=color_map(classes),
        labels={"dsc_classe_consumo_mercado": "Classe", "participacao": "Participação (%)"},
        hover_data={"consumo_mwh": ":,.1f", "participacao": ":.1f"},
    )
    return apply_default_layout(fig)


def monthly_class_line(df: pd.DataFrame, use_moving_average: bool = False):
    if df.empty:
        return empty_figure("Nenhum dado encontrado para os filtros selecionados.")
    grouped = df.groupby(["data_mes", "dsc_classe_consumo_mercado"], as_index=False)["consumo_mwh"].sum()
    if use_moving_average:
        grouped = grouped.sort_values("data_mes")
        grouped["consumo_mwh"] = grouped.groupby("dsc_classe_consumo_mercado")["consumo_mwh"].transform(lambda s: s.rolling(3, min_periods=1).mean())
    classes = grouped["dsc_classe_consumo_mercado"].unique().tolist()
    fig = px.line(
        grouped,
        x="data_mes",
        y="consumo_mwh",
        color="dsc_classe_consumo_mercado",
        color_discrete_map=color_map(classes),
        labels={"data_mes": "Mês", "consumo_mwh": "Consumo (MWh)", "dsc_classe_consumo_mercado": "Classe"},
        hover_data={"consumo_mwh": ":,.1f"},
    )
    return apply_default_layout(fig)


def historical_events_line(df: pd.DataFrame):
    fig = monthly_class_line(df)
    return add_historical_markers(fig)


def year_comparison_bar(df: pd.DataFrame):
    if df.empty:
        return empty_figure("Nenhum dado encontrado para os filtros selecionados.")
    grouped = df.groupby(["ano", "mes"], as_index=False)["consumo_mwh"].sum()
    fig = px.line(
        grouped,
        x="mes",
        y="consumo_mwh",
        color="ano",
        markers=True,
        labels={"mes": "Mês", "consumo_mwh": "Consumo (MWh)", "ano": "Ano"},
        hover_data={"consumo_mwh": ":,.1f"},
    )
    return apply_default_layout(fig)


def class_composition_100_bar(df: pd.DataFrame):
    if df.empty:
        return empty_figure("Nenhum dado encontrado para os filtros selecionados.")
    data = df.copy()
    if "participacao_percentual" not in data or data["participacao_percentual"].isna().all():
        totals = data.groupby(["ano", "nom_agente_distribuidora"])["consumo_mwh"].transform("sum")
        data["participacao_percentual"] = data["consumo_mwh"] / totals * 100
    classes = data["dsc_classe_consumo_mercado"].unique().tolist()
    fig = px.bar(
        data,
        x="nom_agente_distribuidora",
        y="participacao_percentual",
        color="dsc_classe_consumo_mercado",
        color_discrete_map=color_map(classes),
        labels={"nom_agente_distribuidora": "Distribuidora", "participacao_percentual": "Participação (%)"},
        hover_data={"consumo_mwh": ":,.1f", "participacao_percentual": ":.1f"},
    )
    return apply_default_layout(fig)


def class_profile_rankings(df: pd.DataFrame):
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    residential = df[df["dsc_classe_consumo_mercado"].str.contains("Residencial", case=False, na=False)]
    industrial = df[df["dsc_classe_consumo_mercado"].str.contains("Industrial", case=False, na=False)]
    columns = ["nom_agente_distribuidora", "participacao_percentual", "consumo_mwh"]
    return (
        residential.sort_values("participacao_percentual", ascending=False)[columns].head(10),
        industrial.sort_values("participacao_percentual", ascending=False)[columns].head(10),
    )
