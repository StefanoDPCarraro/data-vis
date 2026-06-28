"""Small in-memory aggregators used by the processed SAMP pipeline."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def add_sum_count(store: dict[tuple[Any, ...], dict[str, Any]], key: tuple[Any, ...], value: float | None) -> None:
    if key not in store:
        store[key] = {"consumo_mwh": 0.0, "qtd_linhas": 0, "distribuidoras": set()}
    if value is not None:
        store[key]["consumo_mwh"] += value
    store[key]["qtd_linhas"] += 1


def rows_from_sum_count(store: dict[tuple[Any, ...], dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    rows = []
    for key, metrics in store.items():
        row = dict(zip(columns, key))
        row["consumo_mwh"] = metrics["consumo_mwh"]
        row["qtd_linhas"] = metrics["qtd_linhas"]
        if metrics.get("distribuidoras") is not None:
            row["qtd_distribuidoras"] = len(metrics["distribuidoras"])
        rows.append(row)
    return rows


def participation_rows(
    store: dict[tuple[Any, ...], float],
    key_columns: list[str],
    total_key_indexes: tuple[int, ...],
    total_name: str,
) -> list[dict[str, Any]]:
    totals: dict[tuple[Any, ...], float] = defaultdict(float)
    for key, value in store.items():
        totals[tuple(key[index] for index in total_key_indexes)] += value

    rows = []
    for key, value in store.items():
        total_key = tuple(key[index] for index in total_key_indexes)
        total = totals[total_key]
        row = dict(zip(key_columns, key))
        row["consumo_mwh"] = value
        row[total_name] = total
        row["participacao_percentual"] = (value / total * 100) if total else None
        rows.append(row)
    return rows
