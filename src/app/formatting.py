"""Formatting helpers for Portuguese dashboard labels."""

from __future__ import annotations

from typing import Any


def safe_divide(a: float | int | None, b: float | int | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return float(a) / float(b)


def format_mwh(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.1f} MWh".replace(",", "X").replace(".", ",").replace("X", ".")


def format_percent(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f}%".replace(".", ",")


def format_int(value: Any) -> str:
    if value is None:
        return "-"
    return f"{int(value):,}".replace(",", ".")


def format_period(start: Any, end: Any) -> str:
    if start is None or end is None:
        return "-"
    return f"{start} a {end}"
