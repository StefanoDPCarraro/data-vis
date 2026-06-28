"""Historical events page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.app.data_loader import load_consumo_mensal_classe
from src.app.filters import class_filter, comparison_years_filter, distributor_filter
from src.app.layout import render_header, render_sidebar_context, setup_page
from src.viz.charts import historical_events_line, year_comparison_bar


def render() -> None:
    setup_page("Eventos Históricos")
    render_header("Eventos Históricos", "Observe mudanças temporais em períodos de interesse histórico.")
    st.warning("As marcações indicam períodos de interesse histórico, mas não provam causalidade.")
    st.write("Use esta tela para observar mudanças no padrão temporal, não para provar causalidade.")
    render_sidebar_context()
    df = load_consumo_mensal_classe()
    distributor = distributor_filter(df, key="events_distributor")
    classes = class_filter(df, "events_classes")
    years = comparison_years_filter("events_years")
    filtered = df[(df["ano"].isin(years)) & (df["dsc_classe_consumo_mercado"].isin(classes))]
    if distributor != "Todas":
        filtered = filtered[filtered["nom_agente_distribuidora"] == distributor]

    if filtered.empty:
        st.warning("Nenhum dado encontrado para os filtros selecionados.")
        return

    st.plotly_chart(historical_events_line(filtered), width="stretch")
    st.plotly_chart(year_comparison_bar(filtered), width="stretch")

    monthly = filtered.groupby(["data_mes"], as_index=False)["consumo_mwh"].sum().sort_values("data_mes")
    monthly["variacao_percentual"] = monthly["consumo_mwh"].pct_change() * 100
    changes = monthly.dropna(subset=["variacao_percentual"]).copy()
    changes["variacao_percentual_formatada"] = changes["variacao_percentual"].map(lambda value: f"{value:.1f}%".replace(".", ","))
    left, right = st.columns(2)
    left.subheader("Maiores quedas")
    left.dataframe(changes.nsmallest(10, "variacao_percentual"), width="stretch")
    right.subheader("Maiores crescimentos")
    right.dataframe(changes.nlargest(10, "variacao_percentual"), width="stretch")
