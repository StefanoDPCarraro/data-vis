"""Blocked regional comparison page."""

from __future__ import annotations

import streamlit as st

from src.app.config import GEO_WARNING
from src.app.data_loader import get_geography_status, load_consumo_regiao_classe
from src.app.filters import class_filter, year_range_filter
from src.app.formatting import format_mwh, format_percent
from src.app.layout import render_header, setup_page
from src.viz.charts import empty_figure


TOP_CLASSES = 5


def _collapse_top_classes(df):
    if df.empty:
        return df.copy()
    data = df.copy()
    top_classes = (
        data.groupby("dsc_classe_consumo_mercado")["consumo_mwh"]
        .sum()
        .sort_values(ascending=False)
        .head(TOP_CLASSES)
        .index
    )
    data["classe_agrupada"] = data["dsc_classe_consumo_mercado"].where(data["dsc_classe_consumo_mercado"].isin(top_classes), "Outros")
    return data


def _class_order_by_consumption(df):
    order = df.groupby("classe_agrupada")["consumo_mwh"].sum().sort_values(ascending=False).index.tolist()
    if "Outros" in order:
        order = [value for value in order if value != "Outros"] + ["Outros"]
    return order


def _regional_grouped_bar(df):
    import plotly.express as px

    from src.viz.theme import apply_default_layout, color_map

    if df.empty:
        return empty_figure("Nenhum dado encontrado para os filtros selecionados.")
    data = _collapse_top_classes(df)
    grouped = data.groupby(["regiao", "classe_agrupada"], as_index=False)["consumo_mwh"].sum()
    classes = _class_order_by_consumption(grouped)
    fig = px.bar(
        grouped,
        x="regiao",
        y="consumo_mwh",
        color="classe_agrupada",
        barmode="group",
        color_discrete_map=color_map(classes),
        category_orders={"classe_agrupada": classes},
        labels={"regiao": "Região", "consumo_mwh": "Consumo (MWh)", "classe_agrupada": "Classe"},
        hover_data={"consumo_mwh": ":,.1f"},
    )
    return apply_default_layout(fig)


def _regional_composition_bar(df):
    import plotly.express as px

    from src.viz.theme import apply_default_layout, color_map

    if df.empty:
        return empty_figure("Nenhum dado encontrado para os filtros selecionados.")
    data = _collapse_top_classes(df)
    grouped = data.groupby(["regiao", "classe_agrupada"], as_index=False)["consumo_mwh"].sum()
    totals = grouped.groupby("regiao")["consumo_mwh"].transform("sum")
    grouped["participacao_percentual"] = grouped["consumo_mwh"] / totals * 100
    classes = _class_order_by_consumption(grouped)
    fig = px.bar(
        grouped,
        x="regiao",
        y="participacao_percentual",
        color="classe_agrupada",
        color_discrete_map=color_map(classes),
        category_orders={"classe_agrupada": classes},
        labels={"regiao": "Região", "participacao_percentual": "Participação (%)", "classe_agrupada": "Classe"},
        hover_data={"consumo_mwh": ":,.1f", "participacao_percentual": ":.1f"},
    )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(range=[0, 100])
    return apply_default_layout(fig)


def render() -> None:
    setup_page("Comparativo Regional")
    render_header("Comparativo Regional", "Comparações por região ficam disponíveis quando a dimensão geográfica estiver preenchida.")
    geo = get_geography_status()
    if not geo["available"]:
        st.warning(GEO_WARNING)
        st.write(str(geo["message"]))
        cols = st.columns(3)
        cols[0].metric("Cobertura por linha com região", format_percent(geo["row_coverage"]))
        cols[1].metric("Cobertura por consumo", format_percent(geo["consumption_coverage"]))
        cols[2].metric("Distribuidoras sem geografia", int(geo["missing_distributors"]))
        st.write("A base bruta SAMP não possui UF/região. A Fase 2.1 criou `data/external/distribuidoras_regiao_template.csv` para preenchimento manual.")
        st.write("Para habilitar esta página, preencha `data/external/distribuidoras_regiao.csv` e reexecute a Fase 2.1.")
        return

    if geo["status"] == "parcial":
        st.warning(f"Visualização regional habilitada com cobertura parcial: {format_percent(geo['row_coverage'])} das linhas possuem região.")
    else:
        st.success("Visualização regional habilitada.")
    if "curadoria manual pragmatica" in str(geo["message"]):
        st.info(str(geo["message"]))

    consumo = load_consumo_regiao_classe()
    years = year_range_filter(consumo, "regional_years")
    classes = class_filter(consumo, "regional_classes")
    regioes = sorted(value for value in consumo["regiao"].dropna().unique())
    selected_regions = st.sidebar.multiselect("Regiões", regioes, default=regioes)
    filtered = consumo[(consumo["ano"] >= years[0]) & (consumo["ano"] <= years[1])]
    filtered = filtered[filtered["dsc_classe_consumo_mercado"].isin(classes)]
    filtered = filtered[filtered["regiao"].isin(selected_regions)]

    if filtered.empty:
        st.warning("Nenhum dado encontrado para os filtros selecionados.")
        return

    total = filtered["consumo_mwh"].sum()
    dominant = filtered.groupby("dsc_classe_consumo_mercado")["consumo_mwh"].sum().idxmax()
    cols = st.columns(4)
    cols[0].metric("Consumo regional filtrado", format_mwh(total))
    cols[1].metric("Regiões", filtered["regiao"].nunique())
    cols[2].metric("Classe dominante", dominant)
    cols[3].metric("Cobertura por consumo", format_percent(geo["consumption_coverage"]))
    st.plotly_chart(_regional_grouped_bar(filtered), width="stretch")
    st.plotly_chart(_regional_composition_bar(filtered), width="stretch")
    st.download_button("Baixar dados regionais filtrados (CSV)", filtered.to_csv(index=False).encode("utf-8"), "comparativo_regional_filtrado.csv", "text/csv")
