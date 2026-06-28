"""Inspect raw ANEEL/SAMP CSV files and write discovery reports."""

from __future__ import annotations

import argparse
import csv
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

from src.data.schema_discovery import (
    detect_candidate_columns,
    normalize_column_name,
    probable_meaning,
)

LOGGER = logging.getLogger(__name__)
ENCODINGS = ("utf-8", "utf-8-sig", "latin1", "cp1252")
SEPARATORS = (";", ",", "|", "\t")
UNIQUE_VALUE_LIMIT = 200
NUMERIC_VALUE_LIMIT = 100_000
PHASE_DIR = "fase_1_discovery"


@dataclass
class CsvFormat:
    encoding: str
    separator: str
    columns: list[str]


@dataclass
class NumericStats:
    count: int = 0
    nulls: int = 0
    zeros: int = 0
    negatives: int = 0
    minimum: float | None = None
    maximum: float | None = None
    total: float = 0.0
    values: list[float] | None = None

    def add_null(self) -> None:
        self.nulls += 1

    def add_value(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)
        if value == 0:
            self.zeros += 1
        if value < 0:
            self.negatives += 1
        if self.values is None:
            self.values = []
        if len(self.values) < NUMERIC_VALUE_LIMIT:
            self.values.append(value)

    def as_row(self, file_name: str, year: int | None, column: str, dtype: str) -> dict[str, Any]:
        return {
            "arquivo": file_name,
            "ano_detectado": year,
            "coluna": column,
            "tipo": dtype,
            "minimo": self.minimum,
            "maximo": self.maximum,
            "media": self.total / self.count if self.count else None,
            "mediana": median(self.values) if self.values else None,
            "quantidade_nulos": self.nulls,
            "quantidade_zeros": self.zeros,
            "quantidade_valores_negativos": self.negatives,
        }


def discover_files(raw_dir: Path, pattern: str) -> list[Path]:
    return sorted(raw_dir.glob(pattern))


def resolve_phase_dir(base_dir: Path) -> Path:
    return base_dir if base_dir.name == PHASE_DIR else base_dir / PHASE_DIR


def detect_year_from_filename(path: Path) -> int | None:
    match = re.search(r"(19|20)\d{2}", path.stem)
    return int(match.group(0)) if match else None


def read_text_sample(path: Path, encoding: str, size: int = 131_072) -> str:
    with path.open("r", encoding=encoding, newline="") as handle:
        return handle.read(size)


def detect_csv_format(path: Path) -> CsvFormat:
    best: tuple[int, int, str, str, list[str]] | None = None
    last_error: Exception | None = None

    for encoding in ENCODINGS:
        try:
            sample = read_text_sample(path, encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue

        for separator in SEPARATORS:
            try:
                rows = list(csv.reader(sample.splitlines(), delimiter=separator))
            except csv.Error as exc:
                last_error = exc
                continue
            rows = [row for row in rows if row]
            if not rows:
                continue
            widths = [len(row) for row in rows[:50]]
            mode_width, mode_count = Counter(widths).most_common(1)[0]
            header_width = len(rows[0])
            score = mode_width * 1000 + mode_count - abs(header_width - mode_width)
            candidate = (score, header_width, encoding, separator, rows[0])
            if best is None or candidate > best:
                best = candidate

    if best is None:
        raise ValueError(f"nao foi possivel detectar encoding/separador: {last_error}")

    _, _, encoding, separator, columns = best
    return CsvFormat(encoding=encoding, separator=separator, columns=columns)


def iter_csv_rows(path: Path, fmt: CsvFormat, limit: int | None = None) -> tuple[list[str], list[list[str]]]:
    rows: list[list[str]] = []
    with path.open("r", encoding=fmt.encoding, newline="") as handle:
        reader = csv.reader(handle, delimiter=fmt.separator)
        try:
            header = next(reader)
        except StopIteration:
            return [], []
        for index, row in enumerate(reader, start=1):
            if limit is not None and index > limit:
                break
            rows.append(row)
    return header, rows


def count_data_rows(path: Path, encoding: str) -> int | None:
    try:
        with path.open("r", encoding=encoding, errors="ignore", newline="") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    except OSError:
        return None


def is_null(value: str | None) -> bool:
    return value is None or value.strip() in {"", "NA", "N/A", "NULL", "null", "nan", "NaN"}


def parse_number(value: str | None) -> float | None:
    if is_null(value):
        return None
    text = str(value).strip().replace(" ", "")
    if not re.search(r"\d", text):
        return None
    text = re.sub(r"[^0-9,.\-+]", "", text)
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def infer_type(values: list[str]) -> str:
    present = [value for value in values if not is_null(value)]
    if not present:
        return "null"
    numeric_count = sum(parse_number(value) is not None for value in present)
    if numeric_count == len(present):
        return "numeric"
    date_like = sum(bool(re.match(r"\d{4}-\d{2}-\d{2}$|\d{2}/\d{2}/\d{4}$", value.strip())) for value in present)
    if date_like / len(present) >= 0.8:
        return "date_like"
    return "string"


def row_to_mapping(header: list[str], row: list[str]) -> dict[str, str | None]:
    padded = row + [None] * max(len(header) - len(row), 0)
    return dict(zip(header, padded[: len(header)]))


def inspect_file(path: Path, sample_rows: int, full_scan: bool) -> dict[str, Any]:
    year = detect_year_from_filename(path)
    result: dict[str, Any] = {
        "path": path,
        "file": path.name,
        "year": year,
        "size_mb": round(path.stat().st_size / (1024 * 1024), 3),
        "status": "ok",
        "error": "",
        "format": None,
        "header": [],
        "normalized": [],
        "sample_count": 0,
        "row_count": None,
        "schema_rows": [],
        "null_rows": [],
        "candidate_rows": [],
        "unique_rows": [],
        "numeric_rows": [],
        "duplicate_count": 0,
    }

    try:
        fmt = detect_csv_format(path)
        result["format"] = fmt
        limit = None if full_scan else sample_rows
        header, rows = iter_csv_rows(path, fmt, limit)
        normalized = [normalize_column_name(column) for column in header]
        result["header"] = header
        result["normalized"] = normalized
        result["sample_count"] = len(rows)
        result["row_count"] = len(rows) if full_scan else count_data_rows(path, fmt.encoding)

        column_values: dict[str, list[str]] = {column: [] for column in header}
        nulls = Counter()
        uniques: dict[str, set[str]] = defaultdict(set)
        unique_overflow = Counter()
        numeric_stats: dict[str, NumericStats] = defaultdict(NumericStats)
        fingerprints = Counter()

        candidate_base = detect_candidate_columns(zip(header, normalized))
        categorical_columns = {
            row["coluna_original"]
            for row in candidate_base
            if row["papel_candidato"]
            in {"classe_consumo", "uf", "regiao", "distribuidora", "sigla_distribuidora"}
        }

        for row in rows:
            mapping = row_to_mapping(header, row)
            fingerprints[tuple(mapping.get(column) for column in header)] += 1
            for column in header:
                value = mapping.get(column)
                if len(column_values[column]) < sample_rows:
                    column_values[column].append("" if value is None else value)
                if is_null(value):
                    nulls[column] += 1
                    numeric_stats[column].add_null()
                else:
                    if column in categorical_columns:
                        clean = str(value).strip()
                        if len(uniques[column]) < UNIQUE_VALUE_LIMIT:
                            uniques[column].add(clean)
                        elif clean not in uniques[column]:
                            unique_overflow[column] += 1
                    number = parse_number(value)
                    if number is not None:
                        numeric_stats[column].add_value(number)

        result["duplicate_count"] = sum(count - 1 for count in fingerprints.values() if count > 1)
        scan_label = "arquivo_completo" if full_scan else "amostra"

        inferred_types = {column: infer_type(values) for column, values in column_values.items()}
        for original, norm in zip(header, normalized):
            null_count = nulls[original]
            null_pct = (null_count / len(rows) * 100) if rows else 0
            schema_row = {
                "arquivo": path.name,
                "ano_detectado": year,
                "separador_detectado": fmt.separator,
                "encoding_detectado": fmt.encoding,
                "numero_linhas_lidas_na_amostra": len(rows),
                "coluna_original": original,
                "coluna_normalizada": norm,
                "tipo_inferido": inferred_types[original],
                "quantidade_nulos_na_amostra": null_count,
                "percentual_nulos_na_amostra": round(null_pct, 4),
            }
            result["schema_rows"].append(schema_row)
            result["null_rows"].append(
                {
                    "arquivo": path.name,
                    "ano_detectado": year,
                    "escopo": scan_label,
                    "coluna_original": original,
                    "coluna_normalizada": norm,
                    "quantidade_nulos": null_count,
                    "percentual_nulos": round(null_pct, 4),
                }
            )
            stats = numeric_stats[original]
            if stats.count and inferred_types[original] == "numeric":
                result["numeric_rows"].append(stats.as_row(path.name, year, original, inferred_types[original]))

        for candidate in candidate_base:
            result["candidate_rows"].append(
                {
                    "arquivo": path.name,
                    "ano_detectado": year,
                    **candidate,
                }
            )

        role_by_column: dict[str, list[str]] = defaultdict(list)
        for candidate in candidate_base:
            role_by_column[candidate["coluna_original"]].append(candidate["papel_candidato"])

        for column in sorted(categorical_columns):
            values = sorted(uniques[column])
            norm = normalize_column_name(column)
            result["unique_rows"].append(
                {
                    "arquivo": path.name,
                    "ano_detectado": year,
                    "coluna_original": column,
                    "coluna_normalizada": norm,
                    "papeis_candidatos": ", ".join(sorted(role_by_column[column])),
                    "quantidade_valores_unicos_listados": len(values),
                    "truncado": bool(unique_overflow[column]),
                    "valores_unicos": " | ".join(values),
                }
            )

    except Exception as exc:  # noqa: BLE001 - per-file resilience is required here.
        LOGGER.exception("Falha ao inspecionar %s", path)
        result["status"] = "error"
        result["error"] = str(exc)
    return result


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def build_presence_matrix(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    files = [result["file"] for result in results if result["status"] == "ok"]
    all_columns = sorted({column for result in results for column in result.get("normalized", [])})
    rows = []
    for column in all_columns:
        row = {"coluna_normalizada": column}
        for result in results:
            if result["status"] == "ok":
                row[result["file"]] = column in set(result["normalized"])
        rows.append(row)
    return rows


def write_csv_reports(results: list[dict[str, Any]], output_dir: Path) -> dict[str, list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_summary = []
    schema_rows = []
    null_rows = []
    candidate_rows = []
    unique_rows = []
    numeric_rows = []

    for result in results:
        fmt = result.get("format")
        raw_summary.append(
            {
                "arquivo": result["file"],
                "ano_detectado": result["year"],
                "tamanho_mb": result["size_mb"],
                "encoding_detectado": fmt.encoding if fmt else "",
                "separador_detectado": fmt.separator if fmt else "",
                "numero_colunas": len(result.get("header", [])),
                "numero_linhas": result.get("row_count"),
                "status_leitura": result["status"],
                "mensagem_erro": result["error"],
                "possiveis_duplicidades": result.get("duplicate_count", 0),
            }
        )
        schema_rows.extend(result["schema_rows"])
        null_rows.extend(result["null_rows"])
        candidate_rows.extend(result["candidate_rows"])
        unique_rows.extend(result["unique_rows"])
        numeric_rows.extend(result["numeric_rows"])

    presence_rows = build_presence_matrix(results)
    presence_fields = ["coluna_normalizada"] + [result["file"] for result in results if result["status"] == "ok"]

    write_csv(
        output_dir / "raw_files_summary.csv",
        raw_summary,
        [
            "arquivo",
            "ano_detectado",
            "tamanho_mb",
            "encoding_detectado",
            "separador_detectado",
            "numero_colunas",
            "numero_linhas",
            "status_leitura",
            "mensagem_erro",
            "possiveis_duplicidades",
        ],
    )
    write_csv(
        output_dir / "schema_by_file.csv",
        schema_rows,
        [
            "arquivo",
            "ano_detectado",
            "separador_detectado",
            "encoding_detectado",
            "numero_linhas_lidas_na_amostra",
            "coluna_original",
            "coluna_normalizada",
            "tipo_inferido",
            "quantidade_nulos_na_amostra",
            "percentual_nulos_na_amostra",
        ],
    )
    write_csv(output_dir / "columns_presence_matrix.csv", presence_rows, presence_fields)
    write_csv(
        output_dir / "candidate_columns.csv",
        candidate_rows,
        [
            "arquivo",
            "ano_detectado",
            "coluna_original",
            "coluna_normalizada",
            "papel_candidato",
            "motivo_heuristica",
        ],
    )
    write_csv(
        output_dir / "nulls_by_file.csv",
        null_rows,
        [
            "arquivo",
            "ano_detectado",
            "escopo",
            "coluna_original",
            "coluna_normalizada",
            "quantidade_nulos",
            "percentual_nulos",
        ],
    )
    write_csv(
        output_dir / "unique_values_summary.csv",
        unique_rows,
        [
            "arquivo",
            "ano_detectado",
            "coluna_original",
            "coluna_normalizada",
            "papeis_candidatos",
            "quantidade_valores_unicos_listados",
            "truncado",
            "valores_unicos",
        ],
    )
    write_csv(
        output_dir / "numeric_summary.csv",
        numeric_rows,
        [
            "arquivo",
            "ano_detectado",
            "coluna",
            "tipo",
            "minimo",
            "maximo",
            "media",
            "mediana",
            "quantidade_nulos",
            "quantidade_zeros",
            "quantidade_valores_negativos",
        ],
    )

    return {
        "raw_summary": raw_summary,
        "schema_rows": schema_rows,
        "presence_rows": presence_rows,
        "candidate_rows": candidate_rows,
        "null_rows": null_rows,
        "unique_rows": unique_rows,
        "numeric_rows": numeric_rows,
    }


def summarize_roles(candidate_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    roles: dict[str, set[str]] = defaultdict(set)
    for row in candidate_rows:
        roles[row["papel_candidato"]].add(row["coluna_normalizada"])
    return {role: sorted(values) for role, values in sorted(roles.items())}


def schema_consistency(results: list[dict[str, Any]]) -> tuple[bool, dict[tuple[str, ...], list[str]]]:
    groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for result in results:
        if result["status"] == "ok":
            groups[tuple(result["normalized"])].append(result["file"])
    return len(groups) <= 1, groups


def write_markdown_docs(results: list[dict[str, Any]], report_data: dict[str, list[dict[str, Any]]], docs_dir: Path) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    ok_results = [result for result in results if result["status"] == "ok"]
    error_results = [result for result in results if result["status"] != "ok"]
    years = sorted(result["year"] for result in ok_results if result["year"] is not None)
    consistent, schema_groups = schema_consistency(results)
    roles = summarize_roles(report_data["candidate_rows"])
    all_columns = sorted({row["coluna_normalizada"] for row in report_data["schema_rows"]})

    quality_notes = []
    high_nulls = [row for row in report_data["null_rows"] if float(row["percentual_nulos"] or 0) >= 50]
    negative_numeric = [row for row in report_data["numeric_rows"] if int(row["quantidade_valores_negativos"] or 0) > 0]
    if error_results:
        quality_notes.append(f"{len(error_results)} arquivo(s) falharam na leitura.")
    if high_nulls:
        quality_notes.append(f"{len(high_nulls)} coluna(s)/arquivo(s) tem pelo menos 50% de nulos na amostra.")
    if negative_numeric:
        quality_notes.append(f"{len(negative_numeric)} coluna(s)/arquivo(s) numericas tem valores negativos.")
    if not consistent:
        quality_notes.append(f"Foram encontrados {len(schema_groups)} schemas normalizados distintos.")
    if not quality_notes:
        quality_notes.append("Nenhum problema critico foi identificado na amostra.")

    phase_doc = [
        "# Fase 1 - Discovery SAMP",
        "",
        "## Resumo",
        "",
        f"- Arquivos encontrados: {len(results)}",
        f"- Arquivos lidos com sucesso: {len(ok_results)}",
        f"- Arquivos com erro: {len(error_results)}",
        f"- Anos detectados: {years[0]}-{years[-1]}" if years else "- Anos detectados: nao identificado",
        f"- Schemas consistentes entre anos: {'sim' if consistent else 'nao'}",
        f"- Colunas distintas normalizadas: {len(all_columns)}",
        "",
        "## Colunas candidatas principais",
        "",
    ]
    for role in ("data_periodo", "ano", "mes", "classe_consumo", "distribuidora", "sigla_distribuidora", "uf", "regiao", "consumo", "numero_consumidores", "receita"):
        phase_doc.append(f"- {role}: {', '.join(roles.get(role, [])) or 'nao identificada'}")

    phase_doc.extend(
        [
            "",
            "## Cobertura temporal aparente",
            "",
            "A cobertura temporal foi inferida a partir dos nomes dos arquivos e deve ser validada pela coluna de competencia na Fase 2.",
            "",
            "## Consistencia de schema",
            "",
        ]
    )
    for index, (columns, files) in enumerate(schema_groups.items(), start=1):
        phase_doc.append(f"- Schema {index}: {len(files)} arquivo(s), {len(columns)} coluna(s): {', '.join(files)}")

    phase_doc.extend(["", "## Problemas de qualidade encontrados", ""])
    phase_doc.extend(f"- {note}" for note in quality_notes)
    phase_doc.extend(
        [
            "",
            "## Decisoes para a Fase 2",
            "",
            "- Confirmar a unidade de `vlr_mercado` usando `dsc_detalhe_mercado`, pois ha evidencias de kWh, R$ e outros tipos no mesmo campo de valor.",
            "- Definir a granularidade final: competencia, distribuidora/agente, classe/subclasse, tipo de mercado e detalhe de mercado.",
            "- Padronizar encoding e nomenclatura das colunas sem alterar os arquivos brutos.",
            "- Separar medidas fisicas, monetarias e contagens antes de gerar Parquet.",
            "- Validar se anos recentes estao parciais antes de inclui-los no escopo analitico final.",
            "",
            "## Organizacao documental",
            "",
            f"- Documentos desta fase ficam em `docs/{PHASE_DIR}/`.",
            f"- Relatorios desta fase ficam em `reports/{PHASE_DIR}/`.",
            "- Arquivos gerados anteriormente em locais de fase abreviados foram movidos para a estrutura padronizada.",
        ]
    )
    (docs_dir / "fase_1_discovery.md").write_text("\n".join(phase_doc) + "\n", encoding="utf-8")

    role_by_column: dict[str, set[str]] = defaultdict(set)
    files_by_column: dict[str, set[str]] = defaultdict(set)
    types_by_column: dict[str, set[str]] = defaultdict(set)
    original_by_column: dict[str, set[str]] = defaultdict(set)
    for row in report_data["schema_rows"]:
        norm = row["coluna_normalizada"]
        files_by_column[norm].add(str(row["ano_detectado"] or row["arquivo"]))
        types_by_column[norm].add(row["tipo_inferido"])
        original_by_column[norm].add(row["coluna_original"])
    for row in report_data["candidate_rows"]:
        role_by_column[row["coluna_normalizada"]].add(row["papel_candidato"])

    dictionary_doc = [
        "# Dicionario de dados inicial",
        "",
        "| Coluna original | Coluna normalizada | Arquivos/anos onde aparece | Tipo inferido | Significado provavel | Observacoes |",
        "|---|---|---|---|---|---|",
    ]
    for norm in sorted(files_by_column):
        roles_for_column = sorted(role_by_column.get(norm, []))
        originals = ", ".join(sorted(original_by_column[norm]))
        files = ", ".join(sorted(files_by_column[norm]))
        types = ", ".join(sorted(types_by_column[norm]))
        meaning = probable_meaning(norm, roles_for_column)
        observations = f"Candidata: {', '.join(roles_for_column)}" if roles_for_column else "Confirmar significado."
        dictionary_doc.append(f"| {originals} | {norm} | {files} | {types} | {meaning} | {observations} |")
    (docs_dir / "dicionario_dados_inicial.md").write_text("\n".join(dictionary_doc) + "\n", encoding="utf-8")

    problems_doc = [
        "# Problemas de dados iniciais",
        "",
        "## Arquivos com falha de leitura",
        "",
    ]
    if error_results:
        problems_doc.extend(f"- {result['file']}: {result['error']}" for result in error_results)
    else:
        problems_doc.append("- Nenhum arquivo falhou na leitura.")

    problems_doc.extend(["", "## Diferencas de schema entre anos", ""])
    if consistent:
        problems_doc.append("- Os schemas normalizados parecem consistentes entre os arquivos lidos.")
    else:
        for index, (columns, files) in enumerate(schema_groups.items(), start=1):
            problems_doc.append(f"- Schema {index}: {len(columns)} coluna(s), arquivos: {', '.join(files)}")

    problems_doc.extend(["", "## Colunas ausentes e possiveis mudancas de nomenclatura", ""])
    presence = report_data["presence_rows"]
    file_count = len(ok_results)
    partial_columns = [row["coluna_normalizada"] for row in presence if sum(str(row.get(result["file"])) == "True" for result in ok_results) < file_count]
    if partial_columns:
        problems_doc.extend(f"- {column}" for column in partial_columns)
    else:
        problems_doc.append("- Nenhuma coluna normalizada ausente em parte dos arquivos lidos.")

    problems_doc.extend(["", "## Valores nulos relevantes", ""])
    if high_nulls:
        for row in high_nulls[:100]:
            problems_doc.append(f"- {row['arquivo']} / {row['coluna_normalizada']}: {row['percentual_nulos']}% nulos")
    else:
        problems_doc.append("- Nenhuma coluna com 50% ou mais de nulos na amostra.")

    problems_doc.extend(["", "## Valores negativos em colunas numericas", ""])
    if negative_numeric:
        for row in negative_numeric[:100]:
            problems_doc.append(f"- {row['arquivo']} / {row['coluna']}: {row['quantidade_valores_negativos']} valores negativos")
    else:
        problems_doc.append("- Nenhuma coluna numerica apresentou valores negativos na amostra.")

    problems_doc.extend(
        [
            "",
            "## Classes de consumo e valores inesperados",
            "",
            f"- Validar as listas em `reports/{PHASE_DIR}/unique_values_summary.csv`; o relatorio limita a 200 valores por coluna.",
            "",
            "## Encoding e separador",
            "",
        ]
    )
    encodings = sorted({summary["encoding_detectado"] for summary in report_data["raw_summary"] if summary["encoding_detectado"]})
    separators = sorted({repr(summary["separador_detectado"]) for summary in report_data["raw_summary"] if summary["separador_detectado"]})
    problems_doc.append(f"- Encodings detectados: {', '.join(encodings) or 'nenhum'}")
    problems_doc.append(f"- Separadores detectados: {', '.join(separators) or 'nenhum'}")
    problems_doc.extend(
        [
            "",
            "## Inconsistencias temporais",
            "",
            "- A consistencia temporal interna ainda precisa ser validada contra `dat_competencia` na Fase 2.",
        ]
    )
    (docs_dir / "problemas_dados_iniciais.md").write_text("\n".join(problems_doc) + "\n", encoding="utf-8")


def print_summary(results: list[dict[str, Any]], report_data: dict[str, list[dict[str, Any]]], output_dir: Path, docs_dir: Path) -> None:
    ok_results = [result for result in results if result["status"] == "ok"]
    years = sorted(result["year"] for result in ok_results if result["year"] is not None)
    roles = summarize_roles(report_data["candidate_rows"])
    distinct_columns = {row["coluna_normalizada"] for row in report_data["schema_rows"]}

    print()
    print("Fase 1 - Discovery SAMP concluida")
    print()
    print(f"Arquivos encontrados: {len(results)}")
    if years:
        print(f"Anos detectados: {years[0]}-{years[-1]}")
    else:
        print("Anos detectados: nao identificado")
    print(f"Arquivos lidos com sucesso: {len(ok_results)}")
    print(f"Arquivos com erro: {len(results) - len(ok_results)}")
    print(f"Colunas distintas normalizadas: {len(distinct_columns)}")
    print(f"Colunas candidatas para consumo: {roles.get('consumo', [])}")
    print(f"Colunas candidatas para classe: {roles.get('classe_consumo', [])}")
    print(f"Colunas candidatas para tempo: {sorted(set(roles.get('data_periodo', []) + roles.get('ano', []) + roles.get('mes', [])))}")
    print(f"Relatorios gerados em: {output_dir}/")
    print(f"Documentacao gerada em: {docs_dir}/")
    print()
    print("Proxima fase recomendada:")
    print("Fase 2 - limpeza, padronizacao e geracao das tabelas Parquet.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspeciona CSVs brutos SAMP/ANEEL.")
    parser.add_argument("--raw-dir", default="data/raw", type=Path)
    parser.add_argument("--pattern", default="samp-*.csv")
    parser.add_argument("--sample-rows", default=10_000, type=int)
    parser.add_argument("--full-scan", action="store_true")
    parser.add_argument("--output-dir", default="reports", type=Path)
    parser.add_argument("--docs-dir", default="docs", type=Path)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir = resolve_phase_dir(args.output_dir)
    args.docs_dir = resolve_phase_dir(args.docs_dir)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")
    files = discover_files(args.raw_dir, args.pattern)
    LOGGER.info("Arquivos encontrados: %s", len(files))
    if not files:
        raise SystemExit(f"Nenhum arquivo encontrado em {args.raw_dir} com padrao {args.pattern}")

    results = []
    for path in files:
        LOGGER.info("Inspecionando %s", path)
        results.append(inspect_file(path, args.sample_rows, args.full_scan))

    report_data = write_csv_reports(results, args.output_dir)
    write_markdown_docs(results, report_data, args.docs_dir)
    print_summary(results, report_data, args.output_dir, args.docs_dir)


if __name__ == "__main__":
    main()
