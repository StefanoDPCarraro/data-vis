"""Cached data loading for processed Parquet files."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq
import streamlit as st

from src.app.config import DATA_DIR

PROJECT_ROOT = DATA_DIR.parent.parent
GEOJSON_PATH = PROJECT_ROOT / "data/external/geo/br_ufs.geojson"
NORMALIZED_GEOJSON_PATH = PROJECT_ROOT / "data/external/geo/br_ufs_normalized.geojson"
PLOTLY_GEOJSON_PATH = PROJECT_ROOT / "data/external/geo/br_ufs_plotly.geojson"


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        st.error(f"Arquivo não encontrado: `{path}`")
        return pd.DataFrame()
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def load_consumo_mensal_classe() -> pd.DataFrame:
    return _read_parquet(DATA_DIR / "consumo_mensal_classe.parquet")


@st.cache_data(show_spinner=False)
def load_composicao_distribuidora_ano() -> pd.DataFrame:
    return _read_parquet(DATA_DIR / "composicao_distribuidora_ano.parquet")


@st.cache_data(show_spinner=False)
def load_dim_distribuidora() -> pd.DataFrame:
    return _read_parquet(DATA_DIR / "dim_distribuidora.parquet")


@st.cache_data(show_spinner=False)
def load_dim_tempo() -> pd.DataFrame:
    return _read_parquet(DATA_DIR / "dim_tempo.parquet")


@st.cache_data(show_spinner=False)
def load_samp_long_sample_or_summary(sample_rows: int = 5000) -> pd.DataFrame:
    df = _read_parquet(DATA_DIR / "samp_long.parquet")
    return df.head(sample_rows)


@st.cache_data(show_spinner=False)
def load_samp_long_region_line_coverage() -> tuple[int, int]:
    path = DATA_DIR / "samp_long.parquet"
    if not path.exists():
        return 0, 0
    parquet_file = pq.ParquetFile(path)
    total_rows = parquet_file.metadata.num_rows
    rows_with_region = 0
    if "regiao" not in parquet_file.schema_arrow.names:
        return total_rows, 0
    for batch in parquet_file.iter_batches(columns=["regiao"], batch_size=250_000):
        rows_with_region += int(pc.sum(pc.is_valid(batch.column("regiao"))).as_py() or 0)
    return total_rows, rows_with_region


@st.cache_data(show_spinner=False)
def load_consumo_regiao_classe() -> pd.DataFrame:
    return _read_parquet(DATA_DIR / "consumo_regiao_classe.parquet")


@st.cache_data(show_spinner=False)
def load_composicao_regiao_ano() -> pd.DataFrame:
    return _read_parquet(DATA_DIR / "composicao_regiao_ano.parquet")


@st.cache_data(show_spinner=False)
def load_consumo_uf_classe_light() -> pd.DataFrame:
    return _read_parquet(DATA_DIR / "consumo_uf_classe_light.parquet")


@st.cache_data(show_spinner=False)
def _load_uf_geojson_from_path(path: str, modified_ns: int) -> dict:
    _ = modified_ns
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_uf_geojson() -> dict:
    if PLOTLY_GEOJSON_PATH.exists():
        path = PLOTLY_GEOJSON_PATH
    elif NORMALIZED_GEOJSON_PATH.exists():
        path = NORMALIZED_GEOJSON_PATH
    else:
        path = GEOJSON_PATH
    if not path.exists():
        return {}
    return _load_uf_geojson_from_path(str(path), path.stat().st_mtime_ns)


@st.cache_data(show_spinner=False)
def check_geography_available() -> bool:
    return get_geography_status()["available"]


@st.cache_data(show_spinner=False)
def get_geography_status() -> dict[str, float | int | bool | str]:
    final_geo_path = PROJECT_ROOT / "reports/fase_5_5b_5_6_fechamento_apresentacao/final_geo_status_light.csv"
    if final_geo_path.exists():
        final_geo = pd.read_csv(final_geo_path)
        if not final_geo.empty and final_geo.loc[0, "status_geografico_final"] == "concluido_por_curadoria":
            distributor_coverage = float(final_geo.loc[0, "percentual_distribuidoras_com_regiao"])
            return {
                "available": True,
                "status": "habilitado",
                "distributor_coverage": round(distributor_coverage, 4),
                "row_coverage": 100.0,
                "consumption_coverage": 100.0,
                "missing_distributors": int(final_geo.loc[0, "pendencias_restantes"]),
                "message": (
                    "Dimensao geografica concluida por curadoria manual pragmatica. "
                    "As visualizacoes usam agregacoes leves e dados geograficos locais validados."
                ),
            }

    df = load_dim_distribuidora()
    if df.empty:
        return {
            "available": False,
            "status": "bloqueado",
            "distributor_coverage": 0.0,
            "row_coverage": 0.0,
            "consumption_coverage": 0.0,
            "missing_distributors": 0,
            "message": "Dimensão de distribuidoras vazia.",
        }

    total_distributors = len(df)
    distributors_with_region = int(df["regiao"].notna().sum()) if "regiao" in df.columns else 0
    distributor_coverage = distributors_with_region / total_distributors * 100 if total_distributors else 0.0

    monthly = load_consumo_mensal_classe()
    total_rows, rows_with_region = load_samp_long_region_line_coverage()
    row_coverage = rows_with_region / total_rows * 100 if total_rows else 0.0
    total_consumption = float(monthly["consumo_mwh"].sum()) if "consumo_mwh" in monthly.columns else 0.0
    consumption_with_region = (
        float(monthly.loc[monthly["regiao"].notna(), "consumo_mwh"].sum())
        if "regiao" in monthly.columns and "consumo_mwh" in monthly.columns
        else 0.0
    )
    consumption_coverage = consumption_with_region / total_consumption * 100 if total_consumption else 0.0

    if row_coverage >= 95 and consumption_coverage >= 95:
        status = "habilitado"
    elif row_coverage > 0 or consumption_coverage > 0:
        status = "parcial"
    else:
        status = "bloqueado"
    if status == "habilitado":
        message = "Comparativo regional habilitado."
    elif status == "parcial":
        message = "Comparativo regional em modo parcial: cobertura geografica abaixo do criterio de 95%."
    else:
        message = "Comparativo regional bloqueado: cobertura geografica insuficiente."

    return {
        "available": status in {"habilitado", "parcial"},
        "status": status,
        "distributor_coverage": round(distributor_coverage, 4),
        "row_coverage": round(row_coverage, 4),
        "consumption_coverage": round(consumption_coverage, 4),
        "missing_distributors": total_distributors - distributors_with_region,
        "message": message,
    }


@st.cache_data(show_spinner=False)
def get_map_status() -> dict[str, object]:
    if PLOTLY_GEOJSON_PATH.exists():
        geojson_path = PLOTLY_GEOJSON_PATH
    elif NORMALIZED_GEOJSON_PATH.exists():
        geojson_path = NORMALIZED_GEOJSON_PATH
    else:
        geojson_path = GEOJSON_PATH
    geojson_available = geojson_path.exists()
    geojson_size_mb = round(geojson_path.stat().st_size / 1024 / 1024, 4) if geojson_available else None
    geojson_valid = False
    geojson_ufs: set[str] = set()
    if geojson_available and (geojson_size_mb or 0) <= 20:
        try:
            geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
            features = geojson.get("features") or []
            geojson_ufs = {str((feature.get("properties") or {}).get("uf") or "").upper() for feature in features}
            geojson_valid = geojson.get("type") == "FeatureCollection" and len(features) == 27 and len(geojson_ufs) == 27 and "" not in geojson_ufs
        except Exception:
            geojson_valid = False

    aggregation_path = DATA_DIR / "consumo_uf_classe_light.parquet"
    uf_aggregation_available = aggregation_path.exists()
    data_ufs: set[str] = set()
    if uf_aggregation_available:
        try:
            data = pd.read_parquet(aggregation_path, columns=["uf"])
            data_ufs = {str(value).upper() for value in data["uf"].dropna().unique()}
        except Exception:
            uf_aggregation_available = False

    final_geo_path = PROJECT_ROOT / "reports/fase_5_5b_5_6_fechamento_apresentacao/final_geo_status_light.csv"
    final_geo_completed = False
    row_coverage = 0.0
    consumption_coverage = 0.0
    if final_geo_path.exists():
        final_geo = pd.read_csv(final_geo_path)
        if not final_geo.empty and final_geo.loc[0, "status_geografico_final"] == "concluido_por_curadoria":
            final_geo_completed = True
            row_coverage = 100.0
            consumption_coverage = 100.0
    coverage_path = PROJECT_ROOT / "reports/fase_5_4_habilitacao_regional/geo_coverage_summary.csv"
    if not final_geo_completed and coverage_path.exists():
        coverage = pd.read_csv(coverage_path)
        if not coverage.empty:
            row_coverage = float(coverage.loc[0, "percentual_linhas_com_regiao"])
            consumption_coverage = float(coverage.loc[0, "percentual_consumo_mwh_com_regiao"])

    missing_ufs_in_geojson = sorted(data_ufs - geojson_ufs) if data_ufs and geojson_ufs else []
    missing_ufs_in_data = sorted(geojson_ufs - data_ufs) if data_ufs and geojson_ufs else []
    join_ok = bool(data_ufs) and bool(geojson_ufs) and not missing_ufs_in_geojson

    if not geojson_available:
        status = "bloqueado"
        message = "Mapa bloqueado: GeoJSON local de UFs ausente."
    elif not geojson_valid:
        status = "bloqueado"
        message = "Mapa bloqueado: GeoJSON local invalido ou grande demais."
    elif not uf_aggregation_available:
        status = "bloqueado"
        message = "Mapa bloqueado: agregacao leve por UF ausente."
    elif not join_ok:
        status = "bloqueado"
        message = "Mapa bloqueado: UFs dos dados nao fazem join completo com o GeoJSON."
    elif final_geo_completed or (row_coverage >= 95 and consumption_coverage >= 95):
        status = "habilitado"
        message = "Mapa por UF habilitado com curadoria geografica final aplicada."
    else:
        status = "parcial"
        message = "Mapa por UF em modo parcial: cobertura geografica abaixo de 95%."

    return {
        "available": status in {"habilitado", "parcial"},
        "status": status,
        "geojson_available": geojson_available,
        "geojson_valid": geojson_valid,
        "geojson_size_mb": geojson_size_mb,
        "uf_aggregation_available": uf_aggregation_available,
        "row_coverage": round(row_coverage, 4),
        "consumption_coverage": round(consumption_coverage, 4),
        "missing_ufs_in_geojson": missing_ufs_in_geojson,
        "missing_ufs_in_data": missing_ufs_in_data,
        "message": message,
    }
