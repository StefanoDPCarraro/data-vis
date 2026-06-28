"""Cleaning helpers for SAMP processed pipeline."""

from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.data.schema_discovery import normalize_column_name


STANDARD_COLUMNS = [
    "dat_competencia",
    "dat_geracao_conjunto_dados",
    "dsc_classe_consumo_mercado",
    "dsc_classificacao",
    "dsc_detalhe_consumidor",
    "dsc_detalhe_mercado",
    "dsc_modalidade_tarifaria",
    "dsc_opcao_energia",
    "dsc_posto_tarifario",
    "dsc_sub_classe_consumidor",
    "dsc_sub_grupo_tarifario",
    "ide_agente_acessante",
    "nom_agente_acessante",
    "nom_agente_distribuidora",
    "nom_tipo_mercado",
    "num_cnpj_agente_acessante",
    "num_cnpj_agente_distribuidora",
    "sig_agente_distribuidora",
    "vlr_mercado",
]


def detect_year_from_filename(path: Path) -> int | None:
    match = re.search(r"(19|20)\d{2}", path.stem)
    return int(match.group(0)) if match else None


def discover_raw_files(raw_dir: Path, start_year: int, end_year: int, include_partial_years: bool) -> tuple[list[Path], list[Path]]:
    selected: list[Path] = []
    skipped_partial: list[Path] = []
    for path in sorted(raw_dir.glob("samp-*.csv")):
        year = detect_year_from_filename(path)
        if year is None:
            continue
        if start_year <= year <= end_year:
            selected.append(path)
        elif year > end_year and not include_partial_years:
            skipped_partial.append(path)
        elif include_partial_years and year >= start_year:
            selected.append(path)
    return selected, skipped_partial


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def parse_decimal(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    text = re.sub(r"[^0-9,.\-+]", "", text)
    if not re.search(r"\d", text):
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def month_start(value: date | None) -> date | None:
    return date(value.year, value.month, 1) if value else None


def iter_normalized_rows(path: Path) -> tuple[list[str], Any]:
    handle = path.open("r", encoding="latin1", newline="")
    reader = csv.DictReader(handle, delimiter=";")
    if reader.fieldnames is None:
        handle.close()
        return [], iter(())
    normalized_fields = [normalize_column_name(field) for field in reader.fieldnames]

    def rows() -> Any:
        with handle:
            for raw in reader:
                normalized = {}
                for original, normalized_name in zip(reader.fieldnames or [], normalized_fields):
                    value = raw.get(original)
                    normalized[normalized_name] = value.strip() if isinstance(value, str) else value
                yield normalized

    return normalized_fields, rows()
