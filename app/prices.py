"""Live price lookup via yfinance.

Batch-fetches the latest close for a set of tickers, with a per-ticker fallback
for any the batch call misses. Returns a {SYMBOL: price} dict; symbols that can't
be priced are simply absent (the UI shows them as unpriced rather than crashing).
CASH is handled by the caller (it's always 1.0).
"""
from __future__ import annotations

from typing import Dict, Iterable

import pandas as pd

from app.models import CASH_SYMBOL


def fetch_prices(symbols: Iterable[str]) -> Dict[str, float]:
    import yfinance as yf

    syms = sorted({str(s).strip().upper() for s in symbols if str(s).strip()})
    syms = [s for s in syms if s != CASH_SYMBOL]
    out: Dict[str, float] = {}
    if not syms:
        return out

    # Primary: one batched download of recent closes.
    try:
        data = yf.download(
            syms, period="5d", progress=False, auto_adjust=False, threads=True
        )
        if not data.empty and "Close" in data:
            close = data["Close"]
            if isinstance(close, pd.Series):  # single ticker
                series = close.dropna()
                if len(series):
                    out[syms[0]] = float(series.iloc[-1])
            else:
                for s in syms:
                    if s in close.columns:
                        series = close[s].dropna()
                        if len(series):
                            out[s] = float(series.iloc[-1])
    except Exception:
        pass

    # Fallback: per-ticker fast_info for anything still missing.
    for s in syms:
        if s in out:
            continue
        try:
            fi = yf.Ticker(s).fast_info
            price = fi.get("last_price") or fi.get("lastPrice") or fi.get("previous_close")
            if price:
                out[s] = float(price)
        except Exception:
            continue

    return out
