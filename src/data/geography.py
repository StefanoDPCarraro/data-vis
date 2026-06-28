"""Geographic mapping helpers for electricity distributors."""

from __future__ import annotations

import csv
import unicodedata
from pathlib import Path
from typing import Any

from src.data.schema_discovery import normalize_column_name

VALID_UFS = {
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
}

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

REGION_ALIASES = {
    "norte": "Norte",
    "nordeste": "Nordeste",
    "centro_oeste": "Centro-Oeste",
    "centrooeste": "Centro-Oeste",
    "centro oeste": "Centro-Oeste",
    "sudeste": "Sudeste",
    "sul": "Sul",
}

KEY_PRIORITY = (
    "num_cnpj_agente_distribuidora",
    "sig_agente_distribuidora",
    "nom_agente_distribuidora",
    "nome_normalizado",
)

GEO_COLUMNS = [
    "num_cnpj_agente_distribuidora",
    "sig_agente_distribuidora",
    "nom_agente_distribuidora",
    "nome_normalizado",
    "uf",
    "regiao",
    "fonte_geografia",
    "observacao",
]


def clean_cnpj(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.upper().split())


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    return " ".join(text.split())


def standardize_uf(value: Any) -> tuple[str | None, str | None]:
    text = normalize_text(value).replace(" ", "")
    if not text:
        return None, None
    if text in VALID_UFS:
        return text, None
    return None, f"uf_invalida:{text}"


def standardize_region(value: Any) -> str | None:
    text = normalize_name(value).replace("-", "_")
    if not text:
        return None
    return REGION_ALIASES.get(text, None)


def derive_region_from_uf(uf: str | None) -> str | None:
    return UF_TO_REGION.get(uf or "")


def canonical_key(column: str, value: Any) -> str:
    if column == "num_cnpj_agente_distribuidora":
        return clean_cnpj(value)
    if column in {"nom_agente_distribuidora", "nome_normalizado"}:
        return normalize_name(value)
    return normalize_text(value)


def distributor_name_key(row: dict[str, Any]) -> str:
    return normalize_name(row.get("nom_agente_distribuidora"))


def template_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "num_cnpj_agente_distribuidora": row.get("num_cnpj_agente_distribuidora"),
        "sig_agente_distribuidora": row.get("sig_agente_distribuidora"),
        "nom_agente_distribuidora": row.get("nom_agente_distribuidora"),
        "nome_normalizado": distributor_name_key(row),
        "uf": "",
        "regiao": "",
        "fonte_geografia": "",
        "observacao": "",
    }


def write_geo_template(path: Path, distributors: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [template_row(row) for row in distributors]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=GEO_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def read_geo_file(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"Arquivo geografico sem cabecalho: {path}")
        field_map = {normalize_column_name(field): field for field in reader.fieldnames}
        missing = []
        has_key = any(key in field_map for key in KEY_PRIORITY)
        if not has_key:
            missing.append("uma chave geografica")
        for required in ("uf", "regiao"):
            if required not in field_map:
                missing.append(required)
        if missing:
            raise ValueError(f"Arquivo geografico invalido; campos ausentes: {', '.join(missing)}")

        rows = []
        for raw in reader:
            row = {column: "" for column in GEO_COLUMNS}
            for normalized, original in field_map.items():
                if normalized in row:
                    row[normalized] = raw.get(original, "")
            if not row["nome_normalizado"] and row["nom_agente_distribuidora"]:
                row["nome_normalizado"] = normalize_name(row["nom_agente_distribuidora"])
            rows.append(row)
    return rows, list(field_map)


def normalize_geo_record(row: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    conflicts: list[dict[str, Any]] = []
    uf, uf_error = standardize_uf(row.get("uf"))
    informed_region = standardize_region(row.get("regiao"))
    derived_region = derive_region_from_uf(uf)
    final_region = informed_region or derived_region

    if uf_error:
        conflicts.append(
            {
                "distribuidora": row.get("nom_agente_distribuidora") or row.get("sig_agente_distribuidora"),
                "chave": "",
                "uf_informada": row.get("uf"),
                "regiao_informada": row.get("regiao"),
                "regiao_derivada_uf": derived_region,
                "tipo_conflito": uf_error,
                "fonte": row.get("fonte_geografia"),
            }
        )
    if informed_region and derived_region and informed_region != derived_region:
        conflicts.append(
            {
                "distribuidora": row.get("nom_agente_distribuidora") or row.get("sig_agente_distribuidora"),
                "chave": "",
                "uf_informada": uf,
                "regiao_informada": informed_region,
                "regiao_derivada_uf": derived_region,
                "tipo_conflito": "regiao_diverge_da_uf",
                "fonte": row.get("fonte_geografia"),
            }
        )

    normalized = dict(row)
    normalized["uf"] = uf
    normalized["regiao"] = final_region
    normalized["fonte_geografia"] = row.get("fonte_geografia") or "arquivo_externo"
    return normalized, conflicts


def build_geo_indexes(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, dict[str, Any]]], list[dict[str, Any]]]:
    indexes: dict[str, dict[str, dict[str, Any]]] = {key: {} for key in KEY_PRIORITY}
    conflicts: list[dict[str, Any]] = []
    for raw in rows:
        row, row_conflicts = normalize_geo_record(raw)
        conflicts.extend(row_conflicts)
        for key in KEY_PRIORITY:
            value = canonical_key(key, row.get(key))
            if not value:
                continue
            if value in indexes[key] and indexes[key][value].get("uf") != row.get("uf"):
                conflicts.append(
                    {
                        "distribuidora": row.get("nom_agente_distribuidora") or row.get("sig_agente_distribuidora"),
                        "chave": key,
                        "uf_informada": row.get("uf"),
                        "regiao_informada": row.get("regiao"),
                        "regiao_derivada_uf": derive_region_from_uf(row.get("uf")),
                        "tipo_conflito": "chave_duplicada_com_uf_diferente",
                        "fonte": row.get("fonte_geografia"),
                    }
                )
                continue
            indexes[key][value] = row
    return indexes, conflicts


def match_distributor(row: dict[str, Any], indexes: dict[str, dict[str, dict[str, Any]]]) -> tuple[dict[str, Any] | None, str | None]:
    lookup_row = dict(row)
    lookup_row["nome_normalizado"] = distributor_name_key(row)
    for key in KEY_PRIORITY:
        value = canonical_key(key, lookup_row.get(key))
        if value and value in indexes.get(key, {}):
            return indexes[key][value], key
    return None, None
