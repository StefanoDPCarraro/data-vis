"""Helpers for SAMP raw CSV schema discovery."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ano": ("ano", "anomes", "ano_mes"),
    "mes": ("mes", "mesref", "mes_referencia"),
    "data_periodo": ("data", "dat", "periodo", "competencia", "referencia"),
    "distribuidora": ("distribuidora", "agente", "empresa", "concessionaria", "permissionaria"),
    "sigla_distribuidora": ("sigla", "sig", "sig_agente"),
    "uf": ("uf", "estado"),
    "regiao": ("regiao", "regiao_geografica"),
    "classe_consumo": ("classe", "tipo_consumo", "categoria", "subclasse"),
    "consumo": ("consumo", "energia", "mercado", "mwh", "kwh"),
    "numero_consumidores": ("consumidor", "consumidores", "unidades_consumidoras", "qtd_uc", "num_uc"),
    "receita": ("receita", "faturamento", "tarifa", "valor", "vlr", "rs", "reais"),
}

TEXT_HINTS = {
    "nom": "nome",
    "dsc": "descricao",
    "sig": "sigla",
    "dat": "data",
    "vlr": "valor",
    "num": "numero",
    "qtd": "quantidade",
}


def normalize_column_name(name: str) -> str:
    """Normalize column names for comparison, preserving originals elsewhere."""
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name).strip())
    raw = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", raw)
    normalized = unicodedata.normalize("NFKD", raw)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "coluna_sem_nome"


def detect_candidate_columns(columns: Iterable[tuple[str, str]]) -> list[dict[str, str]]:
    """Return candidate semantic roles from original and normalized names."""
    rows: list[dict[str, str]] = []
    for original, normalized in columns:
        tokens = set(filter(None, normalized.split("_")))
        for role, keywords in ROLE_KEYWORDS.items():
            if role == "consumo" and "classe_consumo" in normalized:
                continue
            matches = []
            for keyword in keywords:
                keyword_norm = normalize_column_name(keyword)
                if keyword_norm in normalized or keyword_norm in tokens:
                    matches.append(keyword)
            if matches:
                rows.append(
                    {
                        "coluna_original": original,
                        "coluna_normalizada": normalized,
                        "papel_candidato": role,
                        "motivo_heuristica": "nome contem " + ", ".join(sorted(set(matches))),
                    }
                )
    return rows


def probable_meaning(normalized: str, roles: Iterable[str]) -> str:
    role_set = set(roles)
    if "consumo" in role_set:
        return "Medida de consumo, energia, mercado ou valor associado ao mercado."
    if "classe_consumo" in role_set:
        return "Categoria, classe ou subclasse de consumo."
    if {"ano", "mes", "data_periodo"} & role_set:
        return "Dimensao temporal, data de competencia ou periodo de referencia."
    if "distribuidora" in role_set:
        return "Identificacao nominal de distribuidora, agente ou empresa."
    if "sigla_distribuidora" in role_set:
        return "Sigla ou codigo abreviado de agente/distribuidora."
    if "uf" in role_set:
        return "Unidade federativa ou estado."
    if "regiao" in role_set:
        return "Regiao geografica."
    if "numero_consumidores" in role_set:
        return "Quantidade de consumidores ou unidades consumidoras."
    if "receita" in role_set:
        return "Receita, faturamento, tarifa ou valor monetario."

    prefix = normalized.split("_", 1)[0]
    if prefix in TEXT_HINTS:
        return f"Campo de {TEXT_HINTS[prefix]} inferido pelo prefixo '{prefix}'."
    return "Significado a confirmar na Fase 2."
