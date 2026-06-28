"""Build geographic distributor dimension and regional quality reports."""

from __future__ import annotations

import argparse
import csv
import logging
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.data.geography import (
    build_geo_indexes,
    distributor_name_key,
    match_distributor,
    read_geo_file,
    template_row,
    write_geo_template,
)

LOGGER = logging.getLogger(__name__)
PHASE_DIR = "fase_2_1_dimensao_geografica"
PHASE1_REPORTS = {
    "raw_files_summary.csv",
    "schema_by_file.csv",
    "columns_presence_matrix.csv",
    "candidate_columns.csv",
    "nulls_by_file.csv",
    "unique_values_summary.csv",
    "numeric_summary.csv",
}
PHASE2_REPORTS = {
    "fase_2_quality_summary.csv",
    "measure_classification_summary.csv",
    "temporal_coverage_by_file.csv",
    "class_consumption_summary.csv",
    "distributor_summary.csv",
    "negative_values_analysis.csv",
}
PHASE_DOC_MOVES = {
    "fase_1_discovery.md": "fase_1_discovery",
    "dicionario_dados_inicial.md": "fase_1_discovery",
    "problemas_dados_iniciais.md": "fase_1_discovery",
    "fase_2_pipeline.md": "fase_2_pipeline",
    "regras_limpeza.md": "fase_2_pipeline",
    "pendencias_fase_2.md": "fase_2_pipeline",
}


def require_pyarrow() -> Any:
    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "A Fase 2.1 precisa de pyarrow. Use `.venv/bin/python -m src.data.build_geography` "
            "ou instale pyarrow no ambiente ativo."
        ) from exc
    return pa, pc, pq


def phase_dir(base_dir: Path) -> Path:
    return base_dir if base_dir.name == PHASE_DIR else base_dir / PHASE_DIR


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def move_file_if_present(source: Path, target: Path, moves: list[dict[str, str]]) -> None:
    if not source.exists() or source.resolve() == target.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        source.unlink()
        action = "removido_duplicado"
    else:
        shutil.move(str(source), str(target))
        action = "movido"
    moves.append({"origem": str(source), "destino": str(target), "acao": action, "compatibilidade": "caminho canonico por fase"})


def reorganize_docs_reports(docs_base: Path, reports_base: Path) -> list[dict[str, str]]:
    moves: list[dict[str, str]] = []
    for phase in ("fase_1_discovery", "fase_2_pipeline", PHASE_DIR):
        (docs_base / phase).mkdir(parents=True, exist_ok=True)
        (reports_base / phase).mkdir(parents=True, exist_ok=True)

    for filename, phase in PHASE_DOC_MOVES.items():
        move_file_if_present(docs_base / filename, docs_base / phase / filename, moves)
    for filename in PHASE1_REPORTS:
        move_file_if_present(reports_base / filename, reports_base / "fase_1_discovery" / filename, moves)
    for filename in PHASE2_REPORTS:
        move_file_if_present(reports_base / filename, reports_base / "fase_2_pipeline" / filename, moves)

    for old, new in ((docs_base / "fase_1", docs_base / "fase_1_discovery"), (docs_base / "fase_2", docs_base / "fase_2_pipeline")):
        if old.exists():
            for file_path in old.glob("*"):
                if file_path.is_file():
                    move_file_if_present(file_path, new / file_path.name, moves)
            try:
                old.rmdir()
            except OSError:
                pass
    return moves


def read_parquet_rows(path: Path, pq: Any) -> list[dict[str, Any]]:
    return pq.read_table(path).to_pylist()


def write_parquet_rows(path: Path, rows: list[dict[str, Any]], pa: Any, pq: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="snappy")


def distributor_metrics(reports_base: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows = read_csv_rows(reports_base / "fase_2_pipeline" / "distributor_summary.csv")
    metrics = {}
    for row in rows:
        key = (row.get("sig_agente_distribuidora") or "", row.get("nom_agente_distribuidora") or "")
        metrics[key] = row
    return metrics


def enrich_distributors(
    distributors: list[dict[str, Any]],
    geo_file: Path,
    geo_exists: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], bool]:
    conflicts: list[dict[str, Any]] = []
    template_created = False
    if not geo_exists:
        enriched = []
        for row in distributors:
            enriched.append(
                {
                    **row,
                    "uf": None,
                    "regiao": None,
                    "fonte_geografia": None,
                    "chave_geografia": None,
                    "geo_match_status": "missing_geo_file",
                }
            )
        return enriched, conflicts, [], template_created

    geo_rows, _ = read_geo_file(geo_file)
    indexes, conflicts = build_geo_indexes(geo_rows)
    enriched = []
    matches = []
    conflict_keys = {
        (conflict.get("chave"), conflict.get("uf_informada"), conflict.get("tipo_conflito"))
        for conflict in conflicts
    }
    for row in distributors:
        match, key = match_distributor(row, indexes)
        status = "unmatched"
        uf = None
        regiao = None
        fonte = None
        if match:
            uf = match.get("uf")
            regiao = match.get("regiao")
            fonte = match.get("fonte_geografia")
            if uf or regiao:
                status = "matched"
                if any(item[0] == key and item[2] for item in conflict_keys):
                    status = "conflict"
            else:
                status = "unmatched"
                key = None
                fonte = None
        enriched_row = {
            **row,
            "uf": uf,
            "regiao": regiao,
            "fonte_geografia": fonte,
            "chave_geografia": key,
            "geo_match_status": status,
        }
        enriched.append(enriched_row)
        matches.append(
            {
                "num_cnpj_agente_distribuidora": row.get("num_cnpj_agente_distribuidora"),
                "sig_agente_distribuidora": row.get("sig_agente_distribuidora"),
                "nom_agente_distribuidora": row.get("nom_agente_distribuidora"),
                "nome_normalizado": distributor_name_key(row),
                "chave_usada": key,
                "fonte_geografia": fonte,
                "geo_match_status": status,
                "uf": uf,
                "regiao": regiao,
            }
        )
    return enriched, conflicts, matches, template_created


def create_template_if_needed(path: Path, distributors: list[dict[str, Any]], create_template: bool) -> bool:
    if path.exists() or not create_template:
        return False
    write_geo_template(path, distributors)
    return True


def samp_long_line_coverage(path: Path, enriched: list[dict[str, Any]], pq: Any) -> tuple[int, int, int]:
    total = pq.ParquetFile(path).metadata.num_rows if path.exists() else 0
    with_uf_distributors = {
        (row.get("sig_agente_distribuidora"), row.get("nom_agente_distribuidora"))
        for row in enriched
        if row.get("uf")
    }
    with_region_distributors = {
        (row.get("sig_agente_distribuidora"), row.get("nom_agente_distribuidora"))
        for row in enriched
        if row.get("regiao")
    }
    if not with_uf_distributors and not with_region_distributors:
        return total, 0, 0

    # This branch is intentionally simple; full Parquet rewrites are done only
    # when a trusted mapping exists and the caller opts in.
    rows = pq.read_table(path, columns=["sig_agente_distribuidora", "nom_agente_distribuidora"]).to_pylist()
    lines_uf = 0
    lines_region = 0
    for row in rows:
        key = (row.get("sig_agente_distribuidora"), row.get("nom_agente_distribuidora"))
        lines_uf += int(key in with_uf_distributors)
        lines_region += int(key in with_region_distributors)
    return total, lines_uf, lines_region


def distributors_without_geo_rows(
    enriched: list[dict[str, Any]],
    metrics: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for row in enriched:
        if row.get("uf") and row.get("regiao"):
            continue
        key = (row.get("sig_agente_distribuidora") or "", row.get("nom_agente_distribuidora") or "")
        metric = metrics.get(key, {})
        rows.append(
            {
                "num_cnpj_agente_distribuidora": row.get("num_cnpj_agente_distribuidora"),
                "sig_agente_distribuidora": row.get("sig_agente_distribuidora"),
                "nom_agente_distribuidora": row.get("nom_agente_distribuidora"),
                "nome_normalizado": distributor_name_key(row),
                "consumo_mwh_total": metric.get("consumo_mwh_total"),
                "primeiro_ano": metric.get("primeiro_ano"),
                "ultimo_ano": metric.get("ultimo_ano"),
                "qtd_linhas": metric.get("qtd_linhas"),
            }
        )
    return rows


def source_summary_rows(enriched: list[dict[str, Any]], metrics: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"qtd_distribuidoras": 0, "qtd_linhas_samp_long": 0, "consumo_mwh_total": 0.0})
    for row in enriched:
        source = row.get("fonte_geografia") or row.get("geo_match_status") or "sem_fonte"
        key_used = row.get("chave_geografia") or "sem_chave"
        metric_key = (row.get("sig_agente_distribuidora") or "", row.get("nom_agente_distribuidora") or "")
        metric = metrics.get(metric_key, {})
        group = grouped[(source, key_used)]
        group["qtd_distribuidoras"] += 1
        group["qtd_linhas_samp_long"] += int(float(metric.get("qtd_linhas") or 0))
        group["consumo_mwh_total"] += float(metric.get("consumo_mwh_total") or 0)
    return [{"fonte_geografia": key[0], "chave_usada": key[1], **value} for key, value in grouped.items()]


def regional_quality_rows(enriched: list[dict[str, Any]], metrics: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"anos": set(), "distribuidoras": set(), "consumo_mwh_total": 0.0, "qtd_linhas": 0})
    total_consumo = 0.0
    for row in enriched:
        region = row.get("regiao") or "sem_regiao"
        metric_key = (row.get("sig_agente_distribuidora") or "", row.get("nom_agente_distribuidora") or "")
        metric = metrics.get(metric_key, {})
        consumo = float(metric.get("consumo_mwh_total") or 0)
        total_consumo += consumo
        group = grouped[region]
        if metric.get("primeiro_ano"):
            group["anos"].add(int(float(metric["primeiro_ano"])))
        if metric.get("ultimo_ano"):
            group["anos"].add(int(float(metric["ultimo_ano"])))
        group["distribuidoras"].add(row.get("sig_agente_distribuidora") or row.get("nom_agente_distribuidora"))
        group["consumo_mwh_total"] += consumo
        group["qtd_linhas"] += int(float(metric.get("qtd_linhas") or 0))
    rows = []
    for region, value in grouped.items():
        rows.append(
            {
                "regiao": region,
                "ano_min": min(value["anos"]) if value["anos"] else "",
                "ano_max": max(value["anos"]) if value["anos"] else "",
                "qtd_distribuidoras": len(value["distribuidoras"]),
                "consumo_mwh_total": value["consumo_mwh_total"],
                "qtd_linhas": value["qtd_linhas"],
                "percentual_consumo_total": (value["consumo_mwh_total"] / total_consumo * 100) if total_consumo else 0,
            }
        )
    return rows


def geo_lookup(enriched: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    lookup = {}
    for row in enriched:
        keys = [
            ("cnpj", row.get("num_cnpj_agente_distribuidora") or ""),
            ("sig_nome", f"{row.get('sig_agente_distribuidora') or ''}|{row.get('nom_agente_distribuidora') or ''}"),
            ("nome", row.get("nom_agente_distribuidora") or ""),
        ]
        for kind, value in keys:
            if value:
                lookup[(kind, value, "")] = row
    return lookup


def find_geo_for_samp_row(row: dict[str, Any], lookup: dict[tuple[str, str, str], dict[str, Any]]) -> dict[str, Any] | None:
    cnpj = row.get("num_cnpj_agente_distribuidora") or ""
    sig_nome = f"{row.get('sig_agente_distribuidora') or ''}|{row.get('nom_agente_distribuidora') or ''}"
    nome = row.get("nom_agente_distribuidora") or ""
    return lookup.get(("cnpj", cnpj, "")) or lookup.get(("sig_nome", sig_nome, "")) or lookup.get(("nome", nome, ""))


def write_aggregate(path: Path, rows: list[dict[str, Any]], pa: Any, pq: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="snappy")


def update_samp_long_and_aggregates(processed_dir: Path, enriched: list[dict[str, Any]], pa: Any, pq: Any) -> bool:
    samp_path = processed_dir / "samp_long.parquet"
    if not samp_path.exists():
        return False

    lookup = geo_lookup(enriched)
    parquet_file = pq.ParquetFile(samp_path)
    temp_path = samp_path.with_suffix(".geo_tmp.parquet")
    writer = pq.ParquetWriter(temp_path, schema=parquet_file.schema_arrow, compression="snappy")

    monthly: dict[tuple[Any, ...], dict[str, Any]] = defaultdict(lambda: {"consumo_mwh": 0.0, "qtd_linhas": 0, "distribuidoras": set()})
    region_class: dict[tuple[Any, ...], dict[str, Any]] = defaultdict(lambda: {"consumo_mwh": 0.0, "qtd_linhas": 0, "distribuidoras": set()})
    uf_class: dict[tuple[Any, ...], dict[str, Any]] = defaultdict(lambda: {"consumo_mwh": 0.0, "qtd_linhas": 0, "distribuidoras": set()})
    comp_dist: dict[tuple[Any, ...], float] = defaultdict(float)
    comp_region: dict[tuple[Any, ...], float] = defaultdict(float)
    comp_uf: dict[tuple[Any, ...], float] = defaultdict(float)

    try:
        for batch in parquet_file.iter_batches(batch_size=50_000):
            rows = batch.to_pylist()
            for row in rows:
                geo = find_geo_for_samp_row(row, lookup)
                if geo:
                    row["uf"] = geo.get("uf")
                    row["regiao"] = geo.get("regiao")
                consumo = row.get("consumo_mwh")
                if row.get("tipo_medida") != "energia" or consumo is None:
                    continue
                data_mes = row.get("data_mes")
                ano = row.get("ano")
                mes = row.get("mes")
                sigla = row.get("sig_agente_distribuidora")
                nome = row.get("nom_agente_distribuidora")
                uf = row.get("uf")
                regiao = row.get("regiao")
                classe = row.get("dsc_classe_consumo_mercado")
                monthly_key = (data_mes, ano, mes, sigla, nome, uf, regiao, classe)
                monthly[monthly_key]["consumo_mwh"] += consumo
                monthly[monthly_key]["qtd_linhas"] += 1
                monthly[monthly_key]["distribuidoras"].add(sigla)
                if regiao:
                    region_key = (ano, mes, data_mes, regiao, classe)
                    region_class[region_key]["consumo_mwh"] += consumo
                    region_class[region_key]["qtd_linhas"] += 1
                    region_class[region_key]["distribuidoras"].add(sigla)
                if uf and regiao:
                    uf_key = (ano, mes, data_mes, uf, regiao, classe)
                    uf_class[uf_key]["consumo_mwh"] += consumo
                    uf_class[uf_key]["qtd_linhas"] += 1
                    uf_class[uf_key]["distribuidoras"].add(sigla)
                comp_dist[(ano, sigla, nome, uf, regiao, classe)] += consumo
                if regiao:
                    comp_region[(ano, regiao, classe)] += consumo
                if uf and regiao:
                    comp_uf[(ano, uf, regiao, classe)] += consumo
            writer.write_table(pa.Table.from_pylist(rows, schema=parquet_file.schema_arrow))
    finally:
        writer.close()

    temp_path.replace(samp_path)

    monthly_rows = [
        {
            "data_mes": key[0],
            "ano": key[1],
            "mes": key[2],
            "sig_agente_distribuidora": key[3],
            "nom_agente_distribuidora": key[4],
            "uf": key[5],
            "regiao": key[6],
            "dsc_classe_consumo_mercado": key[7],
            "consumo_mwh": value["consumo_mwh"],
            "qtd_linhas": value["qtd_linhas"],
        }
        for key, value in monthly.items()
    ]
    region_rows = [
        {
            "ano": key[0],
            "mes": key[1],
            "data_mes": key[2],
            "regiao": key[3],
            "dsc_classe_consumo_mercado": key[4],
            "consumo_mwh": value["consumo_mwh"],
            "qtd_distribuidoras": len(value["distribuidoras"]),
        }
        for key, value in region_class.items()
    ]
    uf_rows = [
        {
            "ano": key[0],
            "mes": key[1],
            "data_mes": key[2],
            "uf": key[3],
            "regiao": key[4],
            "dsc_classe_consumo_mercado": key[5],
            "consumo_mwh": value["consumo_mwh"],
            "qtd_distribuidoras": len(value["distribuidoras"]),
        }
        for key, value in uf_class.items()
    ]

    comp_dist_totals: dict[tuple[Any, ...], float] = defaultdict(float)
    for key, value in comp_dist.items():
        comp_dist_totals[key[:5]] += value
    comp_dist_rows = [
        {
            "ano": key[0],
            "sig_agente_distribuidora": key[1],
            "nom_agente_distribuidora": key[2],
            "uf": key[3],
            "regiao": key[4],
            "dsc_classe_consumo_mercado": key[5],
            "consumo_mwh": value,
            "consumo_total_distribuidora_ano": comp_dist_totals[key[:5]],
            "participacao_percentual": (value / comp_dist_totals[key[:5]] * 100) if comp_dist_totals[key[:5]] else None,
        }
        for key, value in comp_dist.items()
    ]

    comp_region_totals: dict[tuple[Any, ...], float] = defaultdict(float)
    for key, value in comp_region.items():
        comp_region_totals[key[:2]] += value
    comp_region_rows = [
        {
            "ano": key[0],
            "regiao": key[1],
            "dsc_classe_consumo_mercado": key[2],
            "consumo_mwh": value,
            "consumo_total_regiao_ano": comp_region_totals[key[:2]],
            "participacao_percentual": (value / comp_region_totals[key[:2]] * 100) if comp_region_totals[key[:2]] else None,
        }
        for key, value in comp_region.items()
    ]
    comp_uf_totals: dict[tuple[Any, ...], float] = defaultdict(float)
    for key, value in comp_uf.items():
        comp_uf_totals[key[:3]] += value
    comp_uf_rows = [
        {
            "ano": key[0],
            "uf": key[1],
            "regiao": key[2],
            "dsc_classe_consumo_mercado": key[3],
            "consumo_mwh": value,
            "consumo_total_uf_ano": comp_uf_totals[key[:3]],
            "participacao_percentual": (value / comp_uf_totals[key[:3]] * 100) if comp_uf_totals[key[:3]] else None,
        }
        for key, value in comp_uf.items()
    ]

    write_aggregate(processed_dir / "consumo_mensal_classe.parquet", monthly_rows, pa, pq)
    write_aggregate(processed_dir / "consumo_regiao_classe.parquet", region_rows, pa, pq)
    write_aggregate(processed_dir / "consumo_uf_classe.parquet", uf_rows, pa, pq)
    write_aggregate(processed_dir / "composicao_distribuidora_ano.parquet", comp_dist_rows, pa, pq)
    write_aggregate(processed_dir / "composicao_regiao_ano.parquet", comp_region_rows, pa, pq)
    write_aggregate(processed_dir / "composicao_uf_ano.parquet", comp_uf_rows, pa, pq)
    return True


def write_docs(
    docs_dir: Path,
    reports_dir: Path,
    moves: list[dict[str, str]],
    context: dict[str, Any],
) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    coverage = context["coverage"]
    phase_doc = [
        "# Fase 2.1 - Dimensao geografica",
        "",
        "## Objetivo",
        "",
        "Criar uma dimensao geografica confiavel para distribuidoras e preparar as agregacoes regionais sem inferir UF/regiao sem fonte.",
        "",
        "## Entradas",
        "",
        "- `data/processed/dim_distribuidora.parquet`",
        "- `data/processed/samp_long.parquet`",
        "- `data/external/distribuidoras_regiao.csv`, quando existir",
        "",
        "## Saidas",
        "",
        "- `data/processed/dim_distribuidora.parquet` atualizado com metadados de geografia.",
        "- `data/interim/dim_distribuidora_geo_candidates.parquet`.",
        "- `data/external/distribuidoras_regiao_template.csv`, quando arquivo geografico externo nao existe.",
        f"- Relatorios em `{reports_dir}/`.",
        "",
        "## Cobertura",
        "",
        f"- Arquivo geografico externo encontrado: {'sim' if context['geo_exists'] else 'nao'}",
        f"- Distribuidoras com UF: {coverage['distribuidoras_com_uf']} de {coverage['total_distribuidoras']}",
        f"- Distribuidoras com regiao: {coverage['distribuidoras_com_regiao']} de {coverage['total_distribuidoras']}",
        f"- Cobertura por linha em `samp_long`: {coverage['percentual_linhas_com_regiao']}%",
        "",
        "## Agregacoes",
        "",
        f"- Agregacoes regionais regeneradas: {'sim' if context['aggregations_rebuilt'] else 'nao'}",
        "",
        "## Limitacoes",
        "",
        "- UF/regiao nao sao preenchidas quando nao ha fonte externa confiavel.",
        "- Agregacoes regionais existentes permanecem sem valor analitico regional enquanto `regiao` estiver nula.",
    ]
    (docs_dir / "fase_2_1_dimensao_geografica.md").write_text("\n".join(phase_doc) + "\n", encoding="utf-8")

    rules_doc = [
        "# Regras de mapeamento geografico",
        "",
        "- Prioridade de matching: CNPJ, sigla, nome da distribuidora, nome normalizado.",
        "- CNPJ e comparado somente por digitos.",
        "- Siglas sao comparadas em uppercase sem espacos extras.",
        "- Nomes sao comparados sem acentos, em minusculas e com espacos normalizados.",
        "- UF e validada contra a lista oficial de UFs brasileiras.",
        "- Regiao e derivada automaticamente da UF quando a UF existe e a regiao nao foi informada.",
        "- Divergencias entre regiao informada e regiao derivada da UF sao registradas como conflito.",
        "- Sem arquivo externo, o pipeline cria template e nao inventa geografia.",
    ]
    (docs_dir / "regras_mapeamento_geografico.md").write_text("\n".join(rules_doc) + "\n", encoding="utf-8")

    pending_doc = [
        "# Pendencias da Fase 2.1",
        "",
        f"- Distribuidoras sem UF/regiao: {context['without_geo_count']}.",
        f"- Template criado para preenchimento manual: {'sim' if context['template_created'] else 'nao'}.",
        f"- Conflitos encontrados: {context['conflict_count']}.",
        "- O dashboard regional deve aguardar cobertura geografica suficiente para conclusoes regionais.",
    ]
    (docs_dir / "pendencias_fase_2_1.md").write_text("\n".join(pending_doc) + "\n", encoding="utf-8")

    reorg_rows = [
        "# Reorganizacao de docs e reports",
        "",
        "| Origem | Destino | Acao | Compatibilidade |",
        "|---|---|---|---|",
    ]
    if moves:
        for move in moves:
            reorg_rows.append(f"| {move['origem']} | {move['destino']} | {move['acao']} | {move['compatibilidade']} |")
    else:
        reorg_rows.append("| - | - | nenhum arquivo precisava ser movido | estrutura ja estava padronizada |")
    root_docs = sorted(path.name for path in docs_dir.parent.glob("*") if path.is_file())
    root_reports = sorted(path.name for path in reports_dir.parent.glob("*") if path.is_file())
    reorg_rows.extend(
        [
            "",
            "## Arquivos na raiz",
            "",
            f"- `docs/`: {', '.join(root_docs) if root_docs else 'nenhum'}",
            f"- `reports/`: {', '.join(root_reports) if root_reports else 'nenhum'}",
        ]
    )
    (docs_dir / "reorganizacao_docs_reports.md").write_text("\n".join(reorg_rows) + "\n", encoding="utf-8")


def print_summary(context: dict[str, Any]) -> None:
    coverage = context["coverage"]
    print()
    print("Fase 2.1 - Dimensao geografica concluida")
    print()
    print(f"Distribuidoras na dimensao: {coverage['total_distribuidoras']}")
    print(f"Arquivo externo encontrado: {'sim' if context['geo_exists'] else 'nao'}")
    print(f"Distribuidoras com UF: {coverage['distribuidoras_com_uf']}")
    print(f"Distribuidoras com regiao: {coverage['distribuidoras_com_regiao']}")
    print(f"Cobertura por distribuidora: {coverage['percentual_com_regiao']}%")
    print(f"Cobertura por linha em samp_long: {coverage['percentual_linhas_com_regiao']}%")
    print(f"Conflitos encontrados: {context['conflict_count']}")
    print(f"Distribuidoras sem geografia: {context['without_geo_count']}")
    print(f"Template criado: {'sim' if context['template_created'] else 'nao'}")
    print(f"Agregacoes regionais regeneradas: {'sim' if context['aggregations_rebuilt'] else 'nao'}")
    print(f"Docs gerados em: {context['docs_dir']}/")
    print(f"Reports gerados em: {context['reports_dir']}/")
    print()
    print("Proxima fase recomendada:")
    print("Fase 3 - design visual e especificacao das telas.")


def run(args: argparse.Namespace) -> dict[str, Any]:
    pa, _pc, pq = require_pyarrow()
    docs_dir = phase_dir(args.docs_dir)
    reports_dir = phase_dir(args.reports_dir)
    moves = reorganize_docs_reports(args.docs_dir, args.reports_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    args.external_dir.mkdir(parents=True, exist_ok=True)
    args.interim_dir.mkdir(parents=True, exist_ok=True)

    dim_path = args.processed_dir / "dim_distribuidora.parquet"
    samp_long_path = args.processed_dir / "samp_long.parquet"
    if not dim_path.exists():
        raise SystemExit(f"Dimensao de distribuidora nao encontrada: {dim_path}")

    distributors = read_parquet_rows(dim_path, pq)
    geo_file = args.geo_file or (args.external_dir / "distribuidoras_regiao.csv")
    geo_exists = geo_file.exists()
    template_path = args.external_dir / "distribuidoras_regiao_template.csv"
    template_created = create_template_if_needed(template_path, distributors, args.create_template or not geo_exists)

    enriched, conflicts, match_rows, _ = enrich_distributors(distributors, geo_file, geo_exists)
    write_parquet_rows(dim_path, enriched, pa, pq)
    write_parquet_rows(args.interim_dir / "dim_distribuidora_geo_candidates.parquet", [template_row(row) for row in distributors], pa, pq)

    metrics = distributor_metrics(args.reports_dir)
    total_lines, lines_uf, lines_region = samp_long_line_coverage(samp_long_path, enriched, pq)
    total_distributors = len(enriched)
    distributors_with_uf = sum(1 for row in enriched if row.get("uf"))
    distributors_with_region = sum(1 for row in enriched if row.get("regiao"))
    coverage = {
        "total_distribuidoras": total_distributors,
        "distribuidoras_com_uf": distributors_with_uf,
        "distribuidoras_com_regiao": distributors_with_region,
        "percentual_com_uf": round(distributors_with_uf / total_distributors * 100, 4) if total_distributors else 0,
        "percentual_com_regiao": round(distributors_with_region / total_distributors * 100, 4) if total_distributors else 0,
        "total_linhas_samp_long": total_lines,
        "linhas_com_uf": lines_uf,
        "linhas_com_regiao": lines_region,
        "percentual_linhas_com_uf": round(lines_uf / total_lines * 100, 4) if total_lines else 0,
        "percentual_linhas_com_regiao": round(lines_region / total_lines * 100, 4) if total_lines else 0,
    }

    without_geo = distributors_without_geo_rows(enriched, metrics)
    source_rows = source_summary_rows(enriched, metrics)
    regional_rows = regional_quality_rows(enriched, metrics)
    coverage_rows = [coverage]
    write_csv(reports_dir / "geography_mapping_coverage.csv", coverage_rows, list(coverage))
    write_csv(
        reports_dir / "distributors_without_geo.csv",
        without_geo,
        [
            "num_cnpj_agente_distribuidora",
            "sig_agente_distribuidora",
            "nom_agente_distribuidora",
            "nome_normalizado",
            "consumo_mwh_total",
            "primeiro_ano",
            "ultimo_ano",
            "qtd_linhas",
        ],
    )
    write_csv(
        reports_dir / "distributors_geo_conflicts.csv",
        conflicts,
        ["distribuidora", "chave", "uf_informada", "regiao_informada", "regiao_derivada_uf", "tipo_conflito", "fonte"],
    )
    write_csv(
        reports_dir / "distributors_geo_source_summary.csv",
        source_rows,
        ["fonte_geografia", "chave_usada", "qtd_distribuidoras", "qtd_linhas_samp_long", "consumo_mwh_total"],
    )
    write_csv(
        reports_dir / "regional_aggregation_quality.csv",
        regional_rows,
        ["regiao", "ano_min", "ano_max", "qtd_distribuidoras", "consumo_mwh_total", "qtd_linhas", "percentual_consumo_total"],
    )

    aggregations_rebuilt = False
    if geo_exists and distributors_with_region:
        aggregations_rebuilt = update_samp_long_and_aggregates(args.processed_dir, enriched, pa, pq)

    context = {
        "geo_exists": geo_exists,
        "template_created": template_created,
        "aggregations_rebuilt": aggregations_rebuilt,
        "coverage": coverage,
        "conflict_count": len(conflicts),
        "without_geo_count": len(without_geo),
        "docs_dir": docs_dir,
        "reports_dir": reports_dir,
    }
    write_docs(docs_dir, reports_dir, moves, context)
    print_summary(context)
    return context


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Constroi dimensao geografica das distribuidoras.")
    parser.add_argument("--processed-dir", default=Path("data/processed"), type=Path)
    parser.add_argument("--external-dir", default=Path("data/external"), type=Path)
    parser.add_argument("--interim-dir", default=Path("data/interim"), type=Path)
    parser.add_argument("--docs-dir", default=Path("docs"), type=Path)
    parser.add_argument("--reports-dir", default=Path("reports"), type=Path)
    parser.add_argument("--geo-file", default=None, type=Path)
    parser.add_argument("--create-template", action="store_true")
    parser.add_argument("--apply-to-samp-long", action="store_true")
    parser.add_argument("--rebuild-regional-aggregates", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")
    run(args)


if __name__ == "__main__":
    main()
