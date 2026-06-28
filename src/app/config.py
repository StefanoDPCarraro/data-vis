"""Application constants for the Streamlit MVP."""

from pathlib import Path

APP_TITLE = "Consumo de Energia Elétrica no Brasil"
APP_SUBTITLE = "Dashboard interativo com dados ANEEL/SAMP — 2003 a 2025"
DEFAULT_START_YEAR = 2003
DEFAULT_END_YEAR = 2025
DATA_DIR = Path("data/processed")
DOCS_DIR = Path("docs/fase_4_mvp_streamlit")
REPORTS_DIR = Path("reports/fase_4_mvp_streamlit")

EMPTY_FILTER_MESSAGE = "Nenhum dado encontrado para os filtros selecionados."
GEO_WARNING = "Comparações regionais dependem do preenchimento de `data/external/distribuidoras_regiao.csv`."
MAP_WARNING = "Mapa bloqueado até UF/região estarem preenchidos."
MEASURE_NOTICE = "Esta visualização usa apenas `consumo_mwh`, derivado de medidas de energia com unidade confiável."
