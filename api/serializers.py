"""DataFrame -> JSON-safe records.

Pandas/NumPy/Timestamp values aren't directly JSON-serializable; these helpers
normalize NaN -> None and datetimes -> ISO date strings so FastAPI can emit them.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _clean(v: Any):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, (pd.Timestamp,)):
        if pd.isna(v):
            return None
        return v.date().isoformat()
    # numpy scalars -> python scalars
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            return v
    return v


def records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict("records")]
