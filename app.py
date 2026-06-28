"""Streamlit entry point for the ANEEL/SAMP dashboard."""

from __future__ import annotations

import streamlit as st

from src.app.config import APP_SUBTITLE, APP_TITLE
from src.app.layout import setup_page


def main() -> None:
    setup_page("Início")
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)
    st.write(
        "Use o menu lateral para navegar entre as páginas do MVP: Visão Geral, Série Temporal, "
        "Eventos Históricos e Composição por Classe."
    )
    st.info(
        "Comparativo Regional e Mapa estão disponíveis como páginas informativas bloqueadas, "
        "pois UF/região ainda não foram preenchidas."
    )
    st.markdown(
        """
        **Medida oficial de consumo:** `consumo_mwh`.

        **Escopo padrão:** 2003-2025.

        **Geografia:** para habilitar análises regionais, preencha
        `data/external/distribuidoras_regiao.csv` e reexecute a Fase 2.1.
        """
    )


if __name__ == "__main__":
    main()
