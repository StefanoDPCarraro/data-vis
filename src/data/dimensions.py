"""Dimension helpers for SAMP processed outputs."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from src.data.schema_discovery import normalize_column_name
from src.data.transform import fold_text


def clean_cnpj(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def load_distributor_region_lookup(external_dir: Path) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    path = external_dir / "distribuidoras_regiao.csv"
    stats = {"path": str(path), "exists": path.exists(), "rows": 0}
    lookup = {"cnpj": {}, "sigla": {}, "nome": {}}
    if not path.exists():
        return lookup, stats

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return lookup, stats
        field_map = {normalize_column_name(field): field for field in reader.fieldnames}
        for row in reader:
            stats["rows"] += 1
            record = {
                "uf": row.get(field_map.get("uf", ""), "") or None,
                "regiao": row.get(field_map.get("regiao", ""), "") or None,
            }
            cnpj = clean_cnpj(row.get(field_map.get("cnpj", ""), ""))
            sigla = fold_text(row.get(field_map.get("sigla", ""), "")).strip()
            nome = fold_text(row.get(field_map.get("nome", ""), "")).strip()
            if cnpj:
                lookup["cnpj"][cnpj] = record
            if sigla:
                lookup["sigla"][sigla] = record
            if nome:
                lookup["nome"][nome] = record
    return lookup, stats


def match_region(row: dict[str, Any], lookup: dict[str, dict[str, dict[str, str]]]) -> tuple[str | None, str | None, str]:
    cnpj = clean_cnpj(row.get("num_cnpj_agente_distribuidora"))
    sigla = fold_text(row.get("sig_agente_distribuidora")).strip()
    nome = fold_text(row.get("nom_agente_distribuidora")).strip()
    for key, value in (("cnpj", cnpj), ("sigla", sigla), ("nome", nome)):
        if value and value in lookup.get(key, {}):
            record = lookup[key][value]
            return record.get("uf"), record.get("regiao"), key
    return None, None, "sem_match"
