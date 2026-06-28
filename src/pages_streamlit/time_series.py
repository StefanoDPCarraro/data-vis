"""Time series page."""

from __future__ import annotations

import streamlit as st

from src.app.data_loader import load_consumo_mensal_classe
from src.app.filters import apply_common_filters, class_filter, distributor_filter, moving_average_filter, year_range_filter
from src.app.formatting import format_mwh, format_percent, safe_divide
from src.app.layout import render_header, render_sidebar_context, setup_page
from src.viz.annotations import add_historical_markers
from src.viz.charts import monthly_class_line


def render() -> None:
    setup_page("Série Temporal")
    render_header("Série Temporal", "Evolução mensal do consumo por classe.")
    render_sidebar_context()
    df = load_consumo_mensal_classe()
    years = year_range_filter(df, "series_years")
    distributor = distributor_filter(df, include_all=True, key="series_distributor")
    classes = class_filter(df, "series_classes")
    moving = moving_average_filter("series_moving")
    filtered = apply_common_filters(df, years, classes, distributor)

    if filtered.empty:
        st.warning("Nenhum dado encontrado para os filtros selecionados.")
        return

    monthly = filtered.groupby("data_mes", as_index=False)["consumo_mwh"].sum().sort_values("data_mes")
    first = monthly["consumo_mwh"].iloc[0]
    last = monthly["consumo_mwh"].iloc[-1]
    variation = safe_divide(last - first, first)
    col1, col2 = st.columns(2)
    col1.metric("Consumo filtrado", format_mwh(filtered["consumo_mwh"].sum()))
    col2.metric("Variação início-fim", format_percent(variation * 100 if variation is not None else None))

    fig = monthly_class_line(filtered, moving)
    st.plotly_chart(add_historical_markers(fig), width="stretch")
    st.download_button("Baixar dados filtrados (CSV)", filtered.to_csv(index=False).encode("utf-8"), "serie_temporal_filtrada.csv", "text/csv")
    with st.expander("Dados filtrados"):
        st.dataframe(filtered.head(1000), width="stretch")
