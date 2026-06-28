"""Lightweight UF map page."""

from __future__ import annotations

import streamlit as st

from src.app.config import MAP_WARNING
from src.app.data_loader import get_map_status, load_consumo_uf_classe_light, load_uf_geojson
from src.app.formatting import format_mwh, format_percent
from src.app.layout import render_header, setup_page
from src.app.ui_helpers import make_arrow_safe
from src.viz.maps import create_uf_choropleth


def render() -> None:
    setup_page("Mapa")
    render_header("Mapa", "Consumo agregado por Unidade da Federação, com GeoJSON local e agregação leve.")
    status = get_map_status()
    if not status["available"]:
        st.warning(MAP_WARNING)
        st.write(str(status["message"]))
        checklist = {
            "GeoJSON local existe": status["geojson_available"],
            "GeoJSON local válido": status["geojson_valid"],
            "Agregação leve por UF existe": status["uf_aggregation_available"],
            "Join dados ↔ GeoJSON sem UFs faltantes": not bool(status["missing_ufs_in_geojson"]),
        }
        st.dataframe(make_arrow_safe([{"item": key, "ok": value} for key, value in checklist.items()]), width="stretch", hide_index=True)
        return

    if status["status"] == "parcial":
        st.warning(
            "Mapa em modo parcial: "
            f"{format_percent(status['row_coverage'])} das linhas e "
            f"{format_percent(status['consumption_coverage'])} do consumo possuem região."
        )
    else:
        st.success("Mapa por UF habilitado com GeoJSON local validado e agregação leve.")

    with st.expander("Diagnóstico do mapa"):
        st.dataframe(
            make_arrow_safe(
                [
                    {"item": "GeoJSON local existe", "valor_texto": str(status["geojson_available"])},
                    {"item": "GeoJSON local válido", "valor_texto": str(status["geojson_valid"])},
                    {"item": "Tamanho do GeoJSON (MB)", "valor_texto": str(status["geojson_size_mb"])},
                    {"item": "Agregação leve por UF existe", "valor_texto": str(status["uf_aggregation_available"])},
                    {"item": "UFs dos dados sem GeoJSON", "valor_texto": ", ".join(status["missing_ufs_in_geojson"]) or "nenhuma"},
                    {"item": "UFs do GeoJSON sem dados", "valor_texto": ", ".join(status["missing_ufs_in_data"]) or "nenhuma"},
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    data = load_consumo_uf_classe_light()
    geojson = load_uf_geojson()
    if data.empty or not geojson:
        st.warning("Dados leves ou GeoJSON indisponíveis para renderização.")
        return

    years = sorted(data["ano"].dropna().unique())
    classes = sorted(data["dsc_classe_consumo_mercado"].dropna().unique())
    selected_year = st.sidebar.selectbox("Ano", years, index=len(years) - 1)
    selected_classes = st.sidebar.multiselect("Classes", classes, default=classes)
    metric_label = st.sidebar.radio("Métrica", ["Consumo total em MWh", "Participação percentual"], index=0)

    filtered = data[(data["ano"] == selected_year) & (data["dsc_classe_consumo_mercado"].isin(selected_classes))]
    grouped = filtered.groupby(["uf", "regiao"], as_index=False)["consumo_mwh"].sum()
    total = grouped["consumo_mwh"].sum()
    grouped["participacao_percentual"] = grouped["consumo_mwh"] / total * 100 if total else 0
    metric = "consumo_mwh" if metric_label == "Consumo total em MWh" else "participacao_percentual"

    cols = st.columns(4)
    cols[0].metric("Consumo filtrado", format_mwh(total))
    cols[1].metric("UFs com dados", grouped["uf"].nunique())
    dominant = filtered.groupby("dsc_classe_consumo_mercado")["consumo_mwh"].sum().idxmax() if not filtered.empty else "-"
    cols[2].metric("Classe dominante", dominant)
    cols[3].metric("Cobertura por consumo", format_percent(status["consumption_coverage"]))

    try:
        fig = create_uf_choropleth(grouped, geojson, metric)
    except Exception as exc:
        st.error("Mapa bloqueado: GeoJSON ou join UF ↔ dados falhou na validação. Consulte o diagnóstico do mapa.")
        st.exception(exc)
        return
    st.plotly_chart(fig, width="stretch")
    st.dataframe(make_arrow_safe(grouped.sort_values("consumo_mwh", ascending=False)), width="stretch", hide_index=True)
    st.download_button("Baixar dados do mapa (CSV)", grouped.to_csv(index=False).encode("utf-8"), "mapa_uf_filtrado.csv", "text/csv")
