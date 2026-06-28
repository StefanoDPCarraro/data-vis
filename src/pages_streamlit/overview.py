"""Overview page."""

from __future__ import annotations

import streamlit as st

from src.app.data_loader import load_consumo_mensal_classe
from src.app.filters import apply_common_filters, class_filter, distributor_filter, year_range_filter
from src.app.formatting import format_int, format_mwh
from src.app.layout import render_header, render_sidebar_context, setup_page
from src.viz.charts import annual_consumption_line, class_share_bar


def render() -> None:
    setup_page("Visão Geral")
    render_header("Visão Geral", "Resumo do consumo de energia elétrica por classe e distribuidora.")
    render_sidebar_context()
    df = load_consumo_mensal_classe()
    years = year_range_filter(df, "overview_years")
    classes = class_filter(df, "overview_classes")
    distributor = distributor_filter(df, key="overview_distributor")
    filtered = apply_common_filters(df, years, classes, distributor)

    if filtered.empty:
        st.warning("Nenhum dado encontrado para os filtros selecionados.")
        return

    total = filtered["consumo_mwh"].sum()
    class_totals = filtered.groupby("dsc_classe_consumo_mercado")["consumo_mwh"].sum().sort_values(ascending=False)
    kpi = st.columns(5)
    kpi[0].metric("Consumo filtrado", format_mwh(total))
    kpi[1].metric("Período", f"{years[0]}-{years[1]}")
    kpi[2].metric("Distribuidoras", format_int(filtered["sig_agente_distribuidora"].nunique()))
    kpi[3].metric("Classes", format_int(filtered["dsc_classe_consumo_mercado"].nunique()))
    kpi[4].metric("Maior classe", class_totals.index[0] if not class_totals.empty else "-")

    st.plotly_chart(annual_consumption_line(filtered), width="stretch")
    st.plotly_chart(class_share_bar(filtered), width="stretch")
