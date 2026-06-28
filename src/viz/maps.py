"""Map builders for lightweight geographic views."""

from __future__ import annotations

import pandas as pd
import plotly.express as px

from src.viz.charts import empty_figure

VALID_UFS = [
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
]

UF_TO_REGION = {
    "AC": "Norte",
    "AP": "Norte",
    "AM": "Norte",
    "PA": "Norte",
    "RO": "Norte",
    "RR": "Norte",
    "TO": "Norte",
    "AL": "Nordeste",
    "BA": "Nordeste",
    "CE": "Nordeste",
    "MA": "Nordeste",
    "PB": "Nordeste",
    "PE": "Nordeste",
    "PI": "Nordeste",
    "RN": "Nordeste",
    "SE": "Nordeste",
    "DF": "Centro-Oeste",
    "GO": "Centro-Oeste",
    "MT": "Centro-Oeste",
    "MS": "Centro-Oeste",
    "ES": "Sudeste",
    "MG": "Sudeste",
    "RJ": "Sudeste",
    "SP": "Sudeste",
    "PR": "Sul",
    "RS": "Sul",
    "SC": "Sul",
}


def create_uf_map_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    all_ufs = pd.DataFrame({"uf": VALID_UFS})
    data = df.copy()
    if data.empty:
        data = pd.DataFrame(columns=["uf", "regiao", "consumo_mwh", "participacao_percentual"])
    data["uf"] = data["uf"].astype(str).str.upper()
    map_df = all_ufs.merge(data, on="uf", how="left")
    map_df["regiao"] = map_df["regiao"].fillna(map_df["uf"].map(UF_TO_REGION))
    map_df["consumo_mwh"] = pd.to_numeric(map_df["consumo_mwh"], errors="coerce").fillna(0.0)
    total = map_df["consumo_mwh"].sum()
    if "participacao_percentual" in map_df.columns:
        map_df["participacao_percentual"] = pd.to_numeric(map_df["participacao_percentual"], errors="coerce")
    if "participacao_percentual" not in map_df.columns or map_df["participacao_percentual"].isna().any():
        map_df["participacao_percentual"] = (map_df["consumo_mwh"] / total * 100) if total else 0.0
    return map_df


def create_uf_choropleth(df: pd.DataFrame, geojson: dict, metric: str):
    if df.empty:
        return empty_figure("Nenhum dado encontrado para os filtros selecionados.")
    map_df = create_uf_map_dataframe(df)
    label = "Consumo (MWh)" if metric == "consumo_mwh" else "Participação (%)"
    fig = px.choropleth(
        map_df,
        geojson=geojson,
        locations="uf",
        featureidkey="properties.uf",
        color=metric,
        hover_name="uf",
        hover_data={
            "regiao": True,
            "consumo_mwh": ":,.1f",
            "participacao_percentual": ":.2f" if "participacao_percentual" in df.columns else False,
            "uf": False,
        },
        color_continuous_scale="Viridis",
        labels={metric: label},
        projection="mercator",
    )
    fig.update_geos(
        fitbounds="geojson",
        visible=False,
        showcountries=False,
        showcoastlines=False,
        showland=False,
        showlakes=False,
    )
    fig.update_traces(
        marker_line_width=0.5,
        marker_line_color="white",
        customdata=map_df[["regiao", "consumo_mwh", "participacao_percentual"]],
        hovertemplate=(
            "<b>%{location}</b><br>"
            "Região: %{customdata[0]}<br>"
            "Consumo: %{customdata[1]:,.1f} MWh<br>"
            "Participação: %{customdata[2]:.2f}%"
            "<extra></extra>"
        ),
    )
    fig.update_layout(
        template="plotly_white",
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        height=650,
        coloraxis_colorbar={"title": label},
        hovermode="closest",
    )
    return fig
