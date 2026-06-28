"""Measure classification and row transforms for SAMP."""

from __future__ import annotations

import unicodedata
from typing import Any


def fold_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def classify_measure(row: dict[str, Any]) -> tuple[str, str]:
    """Classify VlrMercado without using consumption class as a measure.

    `dsc_classe_consumo_mercado` is intentionally excluded: it is a categorical
    dimension, not evidence that `vlr_mercado` is physical consumption.
    """
    evidence = " ".join(
        fold_text(row.get(column))
        for column in (
            "dsc_detalhe_mercado",
            "nom_tipo_mercado",
            "dsc_detalhe_consumidor",
            "dsc_modalidade_tarifaria",
            "dsc_opcao_energia",
            "dsc_posto_tarifario",
            "dsc_sub_grupo_tarifario",
        )
    )

    if any(token in evidence for token in ("r$", "receita", "icms", "pis", "cofins", "encargo", "subvencao")):
        return "receita", "R$"
    if any(token in evidence for token in ("consumidor", "consumidores", "unidade consumidora", "unidades consumidoras")):
        return "consumidores", "unidade_consumidora"
    if "mwh" in evidence:
        return "energia", "MWh"
    if "kwh" in evidence or "energia" in evidence:
        return "energia", "kWh"
    if any(token in evidence for token in ("mercado", "fio", "tusd", "te")):
        return "outros", "desconhecida"
    if evidence.strip():
        return "outros", "desconhecida"
    return "indefinido", "desconhecida"


def consumo_mwh(vlr_mercado: float | None, tipo_medida: str, unidade_medida: str) -> float | None:
    if vlr_mercado is None or tipo_medida != "energia":
        return None
    if unidade_medida == "MWh":
        return vlr_mercado
    if unidade_medida == "kWh":
        return vlr_mercado / 1000
    return None
