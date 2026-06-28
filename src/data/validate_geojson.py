"""Validate and normalize Brazilian UF GeoJSON files."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.data.geography import VALID_UFS

IBGE_CODE_TO_UF = {
    "11": "RO",
    "12": "AC",
    "13": "AM",
    "14": "RR",
    "15": "PA",
    "16": "AP",
    "17": "TO",
    "21": "MA",
    "22": "PI",
    "23": "CE",
    "24": "RN",
    "25": "PB",
    "26": "PE",
    "27": "AL",
    "28": "SE",
    "29": "BA",
    "31": "MG",
    "32": "ES",
    "33": "RJ",
    "35": "SP",
    "41": "PR",
    "42": "SC",
    "43": "RS",
    "50": "MS",
    "51": "MT",
    "52": "GO",
    "53": "DF",
}

UF_PROPERTY_CANDIDATES = ("uf", "UF", "sigla", "SIGLA", "SIGLA_UF")
CODE_PROPERTY_CANDIDATES = ("CD_UF", "CD_GEOCUF", "codarea", "id")
GEOMETRY_TYPES = {"Polygon", "MultiPolygon"}


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fieldnames} for row in rows)


def uf_from_properties(properties: dict[str, Any]) -> tuple[str | None, str]:
    for key in UF_PROPERTY_CANDIDATES:
        value = str(properties.get(key, "")).strip().upper()
        if value in VALID_UFS:
            return value, key
    for key in CODE_PROPERTY_CANDIDATES:
        value = str(properties.get(key, "")).strip()
        if value in IBGE_CODE_TO_UF:
            return IBGE_CODE_TO_UF[value], key
    return None, ""


def coordinates_in_lonlat(geometry: dict[str, Any]) -> bool:
    coords = geometry.get("coordinates")
    stack = [coords]
    checked = 0
    while stack and checked < 200:
        item = stack.pop()
        if isinstance(item, list) and len(item) >= 2 and all(isinstance(value, (int, float)) for value in item[:2]):
            lon, lat = item[:2]
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                return False
            checked += 1
        elif isinstance(item, list):
            stack.extend(item)
    return checked > 0


def validate_geojson(source: Path, normalized: Path, reports_dir: Path) -> dict[str, Any]:
    validation: list[dict[str, Any]] = []
    inventory: dict[str, dict[str, Any]] = defaultdict(lambda: {"examples": [], "filled": 0})
    normalized_obj: dict[str, Any] | None = None

    def add(item: str, status: str, evidencia: Any, observacao: str = "") -> None:
        validation.append({"item": item, "status": status, "evidencia": evidencia, "observacao": observacao})

    if not source.exists():
        add("arquivo_existe", "erro", source)
        write_csv(reports_dir / "geojson_validation.csv", validation, ["item", "status", "evidencia", "observacao"])
        return {"valid": False, "features": 0, "ufs": [], "missing": sorted(VALID_UFS), "duplicates": []}

    try:
        obj = json.loads(source.read_text(encoding="utf-8"))
        add("json_valido", "ok", source)
    except Exception as exc:
        add("json_valido", "erro", repr(exc))
        write_csv(reports_dir / "geojson_validation.csv", validation, ["item", "status", "evidencia", "observacao"])
        return {"valid": False, "features": 0, "ufs": [], "missing": sorted(VALID_UFS), "duplicates": []}

    features = obj.get("features") if isinstance(obj, dict) else None
    add("tipo_feature_collection", "ok" if obj.get("type") == "FeatureCollection" else "erro", obj.get("type"))
    add("features_presentes", "ok" if isinstance(features, list) else "erro", len(features or []))

    normalized_features = []
    ufs = []
    geometry_errors = 0
    missing_uf_features = 0
    lonlat_errors = 0
    property_source = Counter()

    for feature in features or []:
        properties = dict(feature.get("properties") or {})
        for key, value in properties.items():
            inv = inventory[key]
            if value not in (None, ""):
                inv["filled"] += 1
                if len(inv["examples"]) < 3:
                    inv["examples"].append(str(value))
        uf, source_property = uf_from_properties(properties)
        if uf:
            properties["uf"] = uf
            ufs.append(uf)
            property_source[source_property] += 1
        else:
            missing_uf_features += 1
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in GEOMETRY_TYPES:
            geometry_errors += 1
        if not coordinates_in_lonlat(geometry):
            lonlat_errors += 1
        normalized_features.append({**feature, "properties": properties})

    counts = Counter(ufs)
    duplicates = sorted(uf for uf, count in counts.items() if count > 1)
    missing = sorted(VALID_UFS - set(ufs))
    invalid = sorted(set(ufs) - VALID_UFS)
    valid = (
        obj.get("type") == "FeatureCollection"
        and isinstance(features, list)
        and len(features) == 27
        and not missing
        and not invalid
        and not duplicates
        and missing_uf_features == 0
        and geometry_errors == 0
        and lonlat_errors == 0
    )

    add("qtd_features", "ok" if len(features or []) == 27 else "erro", len(features or []), "Esperado: 27 UFs.")
    add("uf_identificavel", "ok" if missing_uf_features == 0 else "erro", missing_uf_features, f"Fontes usadas: {dict(property_source)}")
    add("ufs_presentes", "ok" if not missing else "erro", ", ".join(sorted(ufs)))
    add("ufs_faltantes", "ok" if not missing else "erro", ", ".join(missing) if missing else "nenhuma")
    add("ufs_duplicadas", "ok" if not duplicates else "erro", ", ".join(duplicates) if duplicates else "nenhuma")
    add("ufs_invalidas", "ok" if not invalid else "erro", ", ".join(invalid) if invalid else "nenhuma")
    add("geometrias_polygon_multipolygon", "ok" if geometry_errors == 0 else "erro", geometry_errors)
    add("coordenadas_lonlat", "ok" if lonlat_errors == 0 else "erro", lonlat_errors)
    add("propriedade_uf_padronizada", "ok" if valid else "erro", "properties.uf")

    inventory_rows = [
        {
            "property_name": key,
            "exemplos": "; ".join(value["examples"]),
            "preenchimento": value["filled"],
            "observacao": "propriedade original do GeoJSON",
        }
        for key, value in sorted(inventory.items())
    ]
    write_csv(reports_dir / "geojson_validation.csv", validation, ["item", "status", "evidencia", "observacao"])
    write_csv(reports_dir / "geojson_properties_inventory.csv", inventory_rows, ["property_name", "exemplos", "preenchimento", "observacao"])

    normalized_obj = {**obj, "features": normalized_features}
    normalized.parent.mkdir(parents=True, exist_ok=True)
    normalized.write_text(json.dumps(normalized_obj, ensure_ascii=False), encoding="utf-8")
    return {"valid": valid, "features": len(features or []), "ufs": sorted(ufs), "missing": missing, "duplicates": duplicates}


def main() -> None:
    parser = argparse.ArgumentParser(description="Valida e normaliza GeoJSON de UFs brasileiras.")
    parser.add_argument("--source", type=Path, default=Path("data/external/geo/br_ufs.geojson"))
    parser.add_argument("--normalized", type=Path, default=Path("data/external/geo/br_ufs_normalized.geojson"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports/fase_5_5_mapa_geojson"))
    args = parser.parse_args()
    result = validate_geojson(args.source, args.normalized, args.reports_dir)
    print(result)


if __name__ == "__main__":
    main()
