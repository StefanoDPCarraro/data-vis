"""Class composition page."""

from __future__ import annotations

import streamlit as st

from src.app.data_loader import load_composicao_distribuidora_ano
from src.app.filters import class_filter, distributor_filter, single_year_filter
from src.app.layout import render_header, render_sidebar_context, setup_page
from src.viz.charts import class_composition_100_bar, class_profile_rankings


def render() -> None:
    setup_page("Composição por Classe")
    render_header("Composição por Classe", "Perfil percentual do consumo por classe, distribuidora e ano.")
    st.info("Esta página mostra composição percentual. Volumes absolutos aparecem apenas como contexto.")
    render_sidebar_context()
    df = load_composicao_distribuidora_ano()
    year = single_year_filter(df, "composition_year")
    distributor = distributor_filter(df, key="composition_distributor")
    classes = class_filter(df, "composition_classes")
    top_n = st.sidebar.slider("Top N distribuidoras por consumo", 5, 30, 12)

    filtered = df[(df["ano"] == year) & (df["dsc_classe_consumo_mercado"].isin(classes))]
    if distributor != "Todas":
        filtered = filtered[filtered["nom_agente_distribuidora"] == distributor]
    else:
        top = filtered.groupby("nom_agente_distribuidora")["consumo_mwh"].sum().nlargest(top_n).index
        filtered = filtered[filtered["nom_agente_distribuidora"].isin(top)]

    if filtered.empty:
        st.warning("Nenhum dado encontrado para os filtros selecionados.")
        return

    st.plotly_chart(class_composition_100_bar(filtered), width="stretch")
    residential, industrial = class_profile_rankings(filtered)
    left, right = st.columns(2)
    left.subheader("Maior participação residencial")
    left.dataframe(residential, width="stretch")
    right.subheader("Maior participação industrial")
    right.dataframe(industrial, width="stretch")
    st.download_button("Baixar composição filtrada (CSV)", filtered.to_csv(index=False).encode("utf-8"), "composicao_filtrada.csv", "text/csv")
    st.dataframe(filtered, width="stretch")
