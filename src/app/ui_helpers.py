"""Small UI helpers for Streamlit rendering."""

from __future__ import annotations

import pandas as pd


def make_arrow_safe(data) -> pd.DataFrame:
    safe = pd.DataFrame(data).copy()
    for column in safe.columns:
        if safe[column].dtype == "object":
            non_null = safe[column].dropna()
            type_names = non_null.map(lambda value: type(value).__name__).unique()
            if len(type_names) > 1:
                safe[column] = safe[column].astype(str)
    return safe
