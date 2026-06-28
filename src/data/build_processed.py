"""Build cleaned SAMP Parquet datasets for dashboard consumption."""

from __future__ import annotations

import argparse
import csv
import logging
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from src.data.clean import (
    STANDARD_COLUMNS,
    detect_year_from_filename,
    discover_raw_files,
    iter_normalized_rows,
    month_start,
    parse_date,
    parse_decimal,
)
from src.data.dimensions import load_distributor_region_lookup, match_region
from src.data.transform import classify_measure, consumo_mwh

LOGGER = logging.getLogger(__name__)
BATCH_SIZE = 50_000
PHASE_DIR = "fase_2_pipeline"
MONTH_NAMES = {
    1: "janeiro",
    2: "fevereiro",
    3: "marco",
    4: "abril",
    5: "maio",
    6: "junho",
    7: "julho",
    8: "agosto",
    9: "setembro",
    10: "outubro",
    11: "novembro",
    12: "dezembro",
}


def require_pyarrow() -> Any:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "A Fase 2 precisa de pyarrow para gerar Parquet. "
            "Instale com `python3 -m pip install pyarrow` e rode novamente."
        ) from exc
    return pa, pq


def resolve_phase_dir(base_dir: Path) -> Path:
    return base_dir if base_dir.name == PHASE_DIR else base_dir / PHASE_DIR


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def parquet_writer(path: Path, schema: Any, pq: Any) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    return pq.ParquetWriter(path, schema=schema, compression="snappy")


def write_batch(writer: Any, rows: list[dict[str, Any]], schema: Any, pa: Any) -> None:
    if rows:
        writer.write_table(pa.Table.from_pylist(rows, schema=schema))
        rows.clear()


def interim_schema(pa: Any) -> Any:
    fields = [(column, pa.string()) for column in STANDARD_COLUMNS]
    fields.extend([("arquivo_origem", pa.string()), ("ano_arquivo", pa.int16())])
    return pa.schema(fields)


def long_schema(pa: Any) -> Any:
    return pa.schema(
        [
            ("data_mes", pa.date32()),
            ("ano", pa.int16()),
            ("mes", pa.int8()),
            ("sig_agente_distribuidora", pa.string()),
            ("nom_agente_distribuidora", pa.string()),
            ("num_cnpj_agente_distribuidora", pa.string()),
            ("uf", pa.string()),
            ("regiao", pa.string()),
            ("dsc_classe_consumo_mercado", pa.string()),
            ("dsc_sub_classe_consumidor", pa.string()),
            ("dsc_detalhe_mercado", pa.string()),
            ("nom_tipo_mercado", pa.string()),
            ("tipo_medida", pa.string()),
            ("unidade_medida", pa.string()),
            ("vlr_mercado", pa.float64()),
            ("consumo_mwh", pa.float64()),
            ("valor_negativo", pa.bool_()),
            ("arquivo_origem", pa.string()),
        ]
    )


def table_schema(pa: Any, rows: list[dict[str, Any]]) -> Any:
    if not rows:
        return pa.schema([("sem_dados", pa.string())])
    fields = []
    sample = rows[0]
    for key, value in sample.items():
        if isinstance(value, bool):
            dtype = pa.bool_()
        elif isinstance(value, int):
            dtype = pa.int64()
        elif isinstance(value, float):
            dtype = pa.float64()
        elif isinstance(value, date):
            dtype = pa.date32()
        else:
            dtype = pa.string()
        fields.append((key, dtype))
    return pa.schema(fields)


def write_parquet_rows(path: Path, rows: list[dict[str, Any]], pa: Any, pq: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = table_schema(pa, rows)
    table = pa.Table.from_pylist(rows or [{"sem_dados": None}], schema=schema)
    pq.write_table(table, path, compression="snappy")


def add_counter(counter: dict[tuple[Any, ...], dict[str, Any]], key: tuple[Any, ...], consumo: float | None, sigla: str | None = None) -> None:
    if key not in counter:
        counter[key] = {"consumo_mwh": 0.0, "qtd_linhas": 0, "distribuidoras": set()}
    if consumo is not None:
        counter[key]["consumo_mwh"] += consumo
    counter[key]["qtd_linhas"] += 1
    if sigla:
        counter[key]["distribuidoras"].add(sigla)


def normalize_for_parquet(row: dict[str, Any], file_name: str, year: int | None) -> dict[str, Any]:
    output = {column: row.get(column) for column in STANDARD_COLUMNS}
    output["arquivo_origem"] = file_name
    output["ano_arquivo"] = year
    return output


def build_time_row(data_mes: date) -> dict[str, Any]:
    return {
        "data_mes": data_mes,
        "ano": data_mes.year,
        "mes": data_mes.month,
        "trimestre": ((data_mes.month - 1) // 3) + 1,
        "semestre": 1 if data_mes.month <= 6 else 2,
        "nome_mes": MONTH_NAMES[data_mes.month],
        "ano_mes": f"{data_mes.year}-{data_mes.month:02d}",
    }


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    pa, pq = require_pyarrow()
    files, skipped_partial = discover_raw_files(args.raw_dir, args.start_year, args.end_year, args.include_partial_years)
    if not files:
        raise SystemExit("Nenhum arquivo bruto selecionado para processamento.")

    args.interim_dir.mkdir(parents=True, exist_ok=True)
    args.processed_dir.mkdir(parents=True, exist_ok=True)
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    args.docs_dir.mkdir(parents=True, exist_ok=True)

    region_lookup, external_stats = load_distributor_region_lookup(args.external_dir)
    interim_writer = parquet_writer(args.interim_dir / "samp_normalized.parquet", interim_schema(pa), pq)
    long_writer = parquet_writer(args.processed_dir / "samp_long.parquet", long_schema(pa), pq)
    interim_batch: list[dict[str, Any]] = []
    long_batch: list[dict[str, Any]] = []

    total_raw = 0
    processed = 0
    measure_counts = Counter()
    unit_counts = Counter()
    year_counts = Counter()
    data_min: date | None = None
    data_max: date | None = None
    temporal_rows: list[dict[str, Any]] = []
    measure_summary: dict[tuple[Any, ...], dict[str, Any]] = defaultdict(lambda: {"contagem_linhas": 0, "soma_vlr_mercado": 0.0, "quantidade_negativos": 0})
    negative_summary: dict[tuple[Any, ...], dict[str, Any]] = defaultdict(lambda: {"quantidade_negativos": 0, "soma_negativos": 0.0, "soma_absoluta_negativos": 0.0})
    class_summary: dict[str, dict[str, Any]] = defaultdict(lambda: {"consumo_mwh_total": 0.0, "qtd_linhas": 0, "anos": set()})
    distributor_summary: dict[tuple[Any, ...], dict[str, Any]] = defaultdict(lambda: {"consumo_mwh_total": 0.0, "qtd_linhas": 0, "anos": set()})
    monthly_class: dict[tuple[Any, ...], dict[str, Any]] = {}
    region_class: dict[tuple[Any, ...], dict[str, Any]] = {}
    comp_dist: dict[tuple[Any, ...], float] = defaultdict(float)
    comp_region: dict[tuple[Any, ...], float] = defaultdict(float)
    distributors: dict[tuple[Any, ...], dict[str, Any]] = {}
    time_values: set[date] = set()
    temporal_mismatches = 0
    rows_region_null = 0
    rows_consumo_null = 0
    rows_negative = 0
    region_match_counts = Counter()

    try:
        for path in files:
            year_file = detect_year_from_filename(path)
            LOGGER.info("Processando %s", path)
            file_rows = 0
            file_dates: list[date] = []
            file_mismatches = 0
            _, rows = iter_normalized_rows(path)
            for row in rows:
                total_raw += 1
                file_rows += 1
                normalized = normalize_for_parquet(row, path.name, year_file)
                interim_batch.append(normalized)

                competencia = parse_date(row.get("dat_competencia"))
                data_mes = month_start(competencia)
                vlr = parse_decimal(row.get("vlr_mercado"))
                tipo_medida, unidade_medida = classify_measure(row)
                consumo = consumo_mwh(vlr, tipo_medida, unidade_medida)
                uf, regiao, match_kind = match_region(row, region_lookup)
                region_match_counts[match_kind] += 1
                valor_negativo = bool(vlr is not None and vlr < 0)
                ano = data_mes.year if data_mes else None
                mes = data_mes.month if data_mes else None

                if data_mes:
                    file_dates.append(data_mes)
                    time_values.add(data_mes)
                    data_min = data_mes if data_min is None else min(data_min, data_mes)
                    data_max = data_mes if data_max is None else max(data_max, data_mes)
                if ano and year_file and ano != year_file:
                    temporal_mismatches += 1
                    file_mismatches += 1
                if regiao is None:
                    rows_region_null += 1
                if consumo is None:
                    rows_consumo_null += 1
                if valor_negativo:
                    rows_negative += 1

                long_row = {
                    "data_mes": data_mes,
                    "ano": ano,
                    "mes": mes,
                    "sig_agente_distribuidora": row.get("sig_agente_distribuidora"),
                    "nom_agente_distribuidora": row.get("nom_agente_distribuidora"),
                    "num_cnpj_agente_distribuidora": row.get("num_cnpj_agente_distribuidora"),
                    "uf": uf,
                    "regiao": regiao,
                    "dsc_classe_consumo_mercado": row.get("dsc_classe_consumo_mercado"),
                    "dsc_sub_classe_consumidor": row.get("dsc_sub_classe_consumidor"),
                    "dsc_detalhe_mercado": row.get("dsc_detalhe_mercado"),
                    "nom_tipo_mercado": row.get("nom_tipo_mercado"),
                    "tipo_medida": tipo_medida,
                    "unidade_medida": unidade_medida,
                    "vlr_mercado": vlr,
                    "consumo_mwh": consumo,
                    "valor_negativo": valor_negativo,
                    "arquivo_origem": path.name,
                }
                long_batch.append(long_row)
                processed += 1
                measure_counts[tipo_medida] += 1
                unit_counts[unidade_medida] += 1
                if ano:
                    year_counts[ano] += 1

                measure_key = (tipo_medida, unidade_medida, row.get("dsc_detalhe_mercado"), row.get("nom_tipo_mercado"))
                measure_summary[measure_key]["contagem_linhas"] += 1
                measure_summary[measure_key]["soma_vlr_mercado"] += vlr or 0.0
                measure_summary[measure_key]["quantidade_negativos"] += int(valor_negativo)

                if valor_negativo:
                    neg_key = (ano, row.get("dsc_detalhe_mercado"), row.get("nom_tipo_mercado"), row.get("dsc_classe_consumo_mercado"))
                    negative_summary[neg_key]["quantidade_negativos"] += 1
                    negative_summary[neg_key]["soma_negativos"] += vlr or 0.0
                    negative_summary[neg_key]["soma_absoluta_negativos"] += abs(vlr or 0.0)

                dist_key = (row.get("sig_agente_distribuidora"), row.get("nom_agente_distribuidora"), row.get("num_cnpj_agente_distribuidora"))
                distributors[dist_key] = {
                    "sig_agente_distribuidora": row.get("sig_agente_distribuidora"),
                    "nom_agente_distribuidora": row.get("nom_agente_distribuidora"),
                    "num_cnpj_agente_distribuidora": row.get("num_cnpj_agente_distribuidora"),
                    "uf": uf,
                    "regiao": regiao,
                }

                if tipo_medida == "energia" and consumo is not None and data_mes is not None:
                    classe = row.get("dsc_classe_consumo_mercado")
                    sigla = row.get("sig_agente_distribuidora")
                    add_counter(
                        monthly_class,
                        (data_mes, ano, mes, sigla, row.get("nom_agente_distribuidora"), uf, regiao, classe),
                        consumo,
                        sigla,
                    )
                    add_counter(region_class, (ano, mes, data_mes, regiao, classe), consumo, sigla)
                    comp_dist[(ano, sigla, row.get("nom_agente_distribuidora"), uf, regiao, classe)] += consumo
                    comp_region[(ano, regiao, classe)] += consumo
                    class_summary[classe]["consumo_mwh_total"] += consumo
                    class_summary[classe]["qtd_linhas"] += 1
                    class_summary[classe]["anos"].add(ano)
                    dsummary_key = (sigla, row.get("nom_agente_distribuidora"), uf, regiao)
                    distributor_summary[dsummary_key]["consumo_mwh_total"] += consumo
                    distributor_summary[dsummary_key]["qtd_linhas"] += 1
                    distributor_summary[dsummary_key]["anos"].add(ano)

                if len(interim_batch) >= BATCH_SIZE:
                    write_batch(interim_writer, interim_batch, interim_schema(pa), pa)
                if len(long_batch) >= BATCH_SIZE:
                    write_batch(long_writer, long_batch, long_schema(pa), pa)

            temporal_rows.append(
                {
                    "arquivo": path.name,
                    "ano_arquivo": year_file,
                    "linhas": file_rows,
                    "data_min": min(file_dates).isoformat() if file_dates else "",
                    "data_max": max(file_dates).isoformat() if file_dates else "",
                    "incompatibilidades_ano_arquivo": file_mismatches,
                }
            )
    finally:
        write_batch(interim_writer, interim_batch, interim_schema(pa), pa)
        write_batch(long_writer, long_batch, long_schema(pa), pa)
        interim_writer.close()
        long_writer.close()

    dim_distribuidora_rows = sorted(distributors.values(), key=lambda row: (row.get("sig_agente_distribuidora") or "", row.get("nom_agente_distribuidora") or ""))
    dim_tempo_rows = [build_time_row(value) for value in sorted(time_values)]
    write_parquet_rows(args.processed_dir / "dim_distribuidora.parquet", dim_distribuidora_rows, pa, pq)
    write_parquet_rows(args.processed_dir / "dim_tempo.parquet", dim_tempo_rows, pa, pq)

    monthly_rows = []
    for key, metrics in monthly_class.items():
        monthly_rows.append(
            dict(
                zip(
                    ["data_mes", "ano", "mes", "sig_agente_distribuidora", "nom_agente_distribuidora", "uf", "regiao", "dsc_classe_consumo_mercado"],
                    key,
                ),
                consumo_mwh=metrics["consumo_mwh"],
                qtd_linhas=metrics["qtd_linhas"],
            )
        )
    region_rows = []
    for key, metrics in region_class.items():
        region_rows.append(
            dict(
                zip(["ano", "mes", "data_mes", "regiao", "dsc_classe_consumo_mercado"], key),
                consumo_mwh=metrics["consumo_mwh"],
                qtd_distribuidoras=len(metrics["distribuidoras"]),
            )
        )

    comp_dist_totals: dict[tuple[Any, ...], float] = defaultdict(float)
    for key, value in comp_dist.items():
        comp_dist_totals[key[:5]] += value
    comp_dist_rows = []
    for key, value in comp_dist.items():
        total = comp_dist_totals[key[:5]]
        comp_dist_rows.append(
            dict(
                zip(["ano", "sig_agente_distribuidora", "nom_agente_distribuidora", "uf", "regiao", "dsc_classe_consumo_mercado"], key),
                consumo_mwh=value,
                consumo_total_distribuidora_ano=total,
                participacao_percentual=(value / total * 100) if total else None,
            )
        )

    comp_region_totals: dict[tuple[Any, ...], float] = defaultdict(float)
    for key, value in comp_region.items():
        comp_region_totals[key[:2]] += value
    comp_region_rows = []
    for key, value in comp_region.items():
        total = comp_region_totals[key[:2]]
        comp_region_rows.append(
            dict(
                zip(["ano", "regiao", "dsc_classe_consumo_mercado"], key),
                consumo_mwh=value,
                consumo_total_regiao_ano=total,
                participacao_percentual=(value / total * 100) if total else None,
            )
        )

    write_parquet_rows(args.processed_dir / "consumo_mensal_classe.parquet", monthly_rows, pa, pq)
    write_parquet_rows(args.processed_dir / "consumo_regiao_classe.parquet", region_rows, pa, pq)
    write_parquet_rows(args.processed_dir / "composicao_distribuidora_ano.parquet", comp_dist_rows, pa, pq)
    write_parquet_rows(args.processed_dir / "composicao_regiao_ano.parquet", comp_region_rows, pa, pq)

    measure_rows = [
        {
            "tipo_medida": key[0],
            "unidade_medida": key[1],
            "dsc_detalhe_mercado": key[2],
            "nom_tipo_mercado": key[3],
            **value,
        }
        for key, value in measure_summary.items()
    ]
    negative_rows = [
        {
            "ano": key[0],
            "dsc_detalhe_mercado": key[1],
            "nom_tipo_mercado": key[2],
            "dsc_classe_consumo_mercado": key[3],
            **value,
        }
        for key, value in negative_summary.items()
    ]
    total_consumo = sum(row["consumo_mwh_total"] for row in class_summary.values())
    class_rows = [
        {
            "classe": classe,
            "consumo_mwh_total": value["consumo_mwh_total"],
            "percentual_do_total": (value["consumo_mwh_total"] / total_consumo * 100) if total_consumo else None,
            "qtd_linhas": value["qtd_linhas"],
            "primeiro_ano": min(value["anos"]) if value["anos"] else None,
            "ultimo_ano": max(value["anos"]) if value["anos"] else None,
        }
        for classe, value in class_summary.items()
    ]
    distributor_rows = [
        {
            "sig_agente_distribuidora": key[0],
            "nom_agente_distribuidora": key[1],
            "uf": key[2],
            "regiao": key[3],
            "consumo_mwh_total": value["consumo_mwh_total"],
            "primeiro_ano": min(value["anos"]) if value["anos"] else None,
            "ultimo_ano": max(value["anos"]) if value["anos"] else None,
            "qtd_linhas": value["qtd_linhas"],
        }
        for key, value in distributor_summary.items()
    ]

    quality_row = {
        "total_linhas_raw": total_raw,
        "total_linhas_processadas": processed,
        "linhas_energia": measure_counts["energia"],
        "linhas_receita": measure_counts["receita"],
        "linhas_consumidores": measure_counts["consumidores"],
        "linhas_indefinidas": measure_counts["indefinido"],
        "percentual_indefinido": (measure_counts["indefinido"] / processed * 100) if processed else 0,
        "consumo_mwh_total": total_consumo,
        "anos_processados": ", ".join(str(year) for year in sorted(year_counts)),
        "data_min": data_min.isoformat() if data_min else "",
        "data_max": data_max.isoformat() if data_max else "",
        "qtd_distribuidoras": len(distributors),
        "qtd_classes": len(class_summary),
        "qtd_linhas_com_regiao_nula": rows_region_null,
        "qtd_linhas_com_consumo_mwh_nulo": rows_consumo_null,
        "qtd_linhas_com_valor_negativo": rows_negative,
    }

    write_csv(args.reports_dir / "fase_2_quality_summary.csv", [quality_row], list(quality_row))
    write_csv(args.reports_dir / "measure_classification_summary.csv", measure_rows, ["tipo_medida", "unidade_medida", "dsc_detalhe_mercado", "nom_tipo_mercado", "contagem_linhas", "soma_vlr_mercado", "quantidade_negativos"])
    write_csv(args.reports_dir / "temporal_coverage_by_file.csv", temporal_rows, ["arquivo", "ano_arquivo", "linhas", "data_min", "data_max", "incompatibilidades_ano_arquivo"])
    write_csv(args.reports_dir / "class_consumption_summary.csv", class_rows, ["classe", "consumo_mwh_total", "percentual_do_total", "qtd_linhas", "primeiro_ano", "ultimo_ano"])
    write_csv(args.reports_dir / "distributor_summary.csv", distributor_rows, ["sig_agente_distribuidora", "nom_agente_distribuidora", "uf", "regiao", "consumo_mwh_total", "primeiro_ano", "ultimo_ano", "qtd_linhas"])
    write_csv(args.reports_dir / "negative_values_analysis.csv", negative_rows, ["ano", "dsc_detalhe_mercado", "nom_tipo_mercado", "dsc_classe_consumo_mercado", "quantidade_negativos", "soma_negativos", "soma_absoluta_negativos"])

    context = {
        "files": files,
        "skipped_partial": skipped_partial,
        "quality": quality_row,
        "measure_counts": measure_counts,
        "unit_counts": unit_counts,
        "external_stats": external_stats,
        "region_match_counts": region_match_counts,
        "temporal_mismatches": temporal_mismatches,
        "processed_dir": args.processed_dir,
        "reports_dir": args.reports_dir,
        "docs_dir": args.docs_dir,
        "data_min": data_min,
        "data_max": data_max,
    }
    write_docs(args, context)
    return context


def write_docs(args: argparse.Namespace, context: dict[str, Any]) -> None:
    quality = context["quality"]
    generated = [
        "samp_long.parquet",
        "consumo_mensal_classe.parquet",
        "consumo_regiao_classe.parquet",
        "composicao_distribuidora_ano.parquet",
        "composicao_regiao_ano.parquet",
        "dim_distribuidora.parquet",
        "dim_tempo.parquet",
    ]
    phase_doc = [
        "# Fase 2 - Pipeline SAMP",
        "",
        "## Objetivo",
        "",
        "Limpar, padronizar, classificar medidas e gerar arquivos Parquet processados para alimentar o dashboard.",
        "",
        "## Arquivos lidos",
        "",
        *[f"- {path.name}" for path in context["files"]],
        "",
        "## Anos processados",
        "",
        f"- {quality['anos_processados']}",
        "",
        "## Regras de classificacao de medida",
        "",
        "- `dsc_classe_consumo_mercado` e uma dimensao categorica e nao e usada como evidencia de medida de consumo.",
        "- `vlr_mercado` so vira `consumo_mwh` quando `dsc_detalhe_mercado` e campos relacionados indicam energia e unidade confiavel.",
        "- Valores em kWh sao convertidos para MWh dividindo por 1000.",
        "- Valores negativos sao preservados e reportados.",
        "",
        "## Parquets gerados",
        "",
        *[f"- `{name}`" for name in generated],
        "",
        "## Principais pendencias",
        "",
        f"- Ver `docs/{PHASE_DIR}/pendencias_fase_2.md`.",
        "",
        "## Organizacao documental",
        "",
        f"- Documentos desta fase ficam em `docs/{PHASE_DIR}/`.",
        f"- Relatorios desta fase ficam em `reports/{PHASE_DIR}/`.",
        "- Arquivos gerados anteriormente na raiz de `reports/` ou em `docs/fase_2/` foram movidos para a estrutura padronizada.",
    ]
    (args.docs_dir / "fase_2_pipeline.md").write_text("\n".join(phase_doc) + "\n", encoding="utf-8")

    rules_doc = [
        "# Regras de limpeza",
        "",
        "- Colunas sao normalizadas com a mesma logica da Fase 1: minusculas, sem acentos e com separadores `_`.",
        "- `dat_competencia` e convertida para data; `ano`, `mes` e `data_mes` sao derivados dela.",
        "- `dsc_classificacao` e mantida no schema e preenchida com nulo quando ausente em 2021-2026.",
        "- `vlr_mercado` e convertido para numero decimal preservando negativos.",
        "- UF e regiao vem de `data/external/distribuidoras_regiao.csv` quando existir; caso contrario ficam nulas.",
        "- Unidade de medida e derivada dos campos de detalhe de mercado e contexto tarifario, nunca da classe de consumo.",
    ]
    (args.docs_dir / "regras_limpeza.md").write_text("\n".join(rules_doc) + "\n", encoding="utf-8")

    skipped = ", ".join(path.name for path in context["skipped_partial"]) or "nenhum"
    external = context["external_stats"]
    region_available = "sim" if external.get("exists") else "nao"
    pending_doc = [
        "# Pendencias da Fase 2",
        "",
        f"- Medidas classificadas como indefinidas: {quality['linhas_indefinidas']}.",
        f"- UF/regiao disponivel por arquivo externo: {region_available}.",
        f"- Linhas com regiao nula: {quality['qtd_linhas_com_regiao_nula']}.",
        f"- Unidades de medida desconhecidas: {context['unit_counts'].get('desconhecida', 0)}.",
        f"- Arquivos parciais fora do escopo padrao: {skipped}.",
        f"- Incompatibilidades entre `ano_arquivo` e `dat_competencia`: {context['temporal_mismatches']}.",
        "- Validar manualmente a classificacao de `dsc_detalhe_mercado` antes de tratar `consumo_mwh` como serie final.",
    ]
    (args.docs_dir / "pendencias_fase_2.md").write_text("\n".join(pending_doc) + "\n", encoding="utf-8")


def print_summary(context: dict[str, Any]) -> None:
    quality = context["quality"]
    region_available = "sim" if context["external_stats"].get("exists") else "nao"
    print()
    print("Fase 2 - Pipeline SAMP concluida")
    print()
    print(f"Arquivos lidos: {len(context['files'])}")
    print(f"Anos processados: {quality['anos_processados']}")
    print(f"Linhas brutas: {quality['total_linhas_raw']}")
    print(f"Linhas processadas: {quality['total_linhas_processadas']}")
    print(f"Linhas classificadas como energia: {quality['linhas_energia']}")
    print(f"Linhas com consumo_mwh valido: {quality['total_linhas_processadas'] - quality['qtd_linhas_com_consumo_mwh_nulo']}")
    print(f"Linhas com medida indefinida: {quality['linhas_indefinidas']}")
    print(f"Distribuidoras: {quality['qtd_distribuidoras']}")
    print(f"Classes de consumo: {quality['qtd_classes']}")
    print(f"Periodo: {quality['data_min'][:7]} a {quality['data_max'][:7]}")
    print(f"Regiao disponivel: {region_available}")
    print(f"Parquets gerados em: {context['processed_dir']}/")
    print(f"Relatorios gerados em: {context['reports_dir']}/")
    print(f"Documentacao gerada em: {context['docs_dir']}/")
    print()
    print("Proxima fase recomendada:")
    print("Fase 3 - design visual e prototipo das visualizacoes no Streamlit.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Constroi dados processados SAMP em Parquet.")
    parser.add_argument("--raw-dir", default=Path("data/raw"), type=Path)
    parser.add_argument("--interim-dir", default=Path("data/interim"), type=Path)
    parser.add_argument("--processed-dir", default=Path("data/processed"), type=Path)
    parser.add_argument("--external-dir", default=Path("data/external"), type=Path)
    parser.add_argument("--reports-dir", default=Path("reports"), type=Path)
    parser.add_argument("--docs-dir", default=Path("docs"), type=Path)
    parser.add_argument("--start-year", default=2003, type=int)
    parser.add_argument("--end-year", default=2025, type=int)
    parser.add_argument("--include-partial-years", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.reports_dir = resolve_phase_dir(args.reports_dir)
    args.docs_dir = resolve_phase_dir(args.docs_dir)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")
    context = run_pipeline(args)
    print_summary(context)


if __name__ == "__main__":
    main()
