"""E*TRADE portfolio-export parser -> ImportResult.

E*TRADE's downloadable portfolio CSV has a preamble (account name, date), then a
header row containing 'Symbol' and 'Qty', then position rows, then a
cash/total/disclaimer section. This parser is deliberately tolerant: it locates
the header by content and maps columns by fuzzy name match.

Produces:
  * one Account (name parsed from the preamble if possible, else the default)
  * a Holding per position row
  * a Balance from the 'CASH & CASH ALTERNATIVES' row's Value column, if present
"""
from __future__ import annotations

import io
import re
from typing import List, Optional

import pandas as pd

from app.models import Account, Balance, Holding, ImportResult
from app.sources.base import PortfolioSource, to_float

CASH_ROW_SYMBOLS = {"CASH & CASH ALTERNATIVES", "CASH"}
TOTAL_ROW_SYMBOLS = {"TOTAL", "TOTALS"}


def _read_text(file) -> str:
    if hasattr(file, "read"):
        data = file.read()
        return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    with open(file, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _find_col(columns, *needles) -> Optional[str]:
    for col in columns:
        low = col.lower()
        if all(n in low for n in needles):
            return col
    return None


def _account_name_from_preamble(lines, header_idx, default) -> str:
    for line in lines[:header_idx]:
        text = line.strip().strip('"')
        if not text:
            continue
        m = re.search(r"holdings\s+for\s+(.+)", text, re.IGNORECASE)
        if m:
            # Trim a trailing account number like "(####-1234)".
            return re.sub(r"\s*\(.*\)\s*$", "", m.group(1)).strip() or default
    return default


class EtradeCSVSource(PortfolioSource):
    name = "etrade_csv"

    def __init__(self, file, account: Optional[str] = None):
        self.file = file
        # Explicit account label (from the UI). If unset, fall back to a name
        # parsed from the export preamble, then to "Brokerage".
        self.account = account.strip() if account else None

    def fetch(self) -> ImportResult:
        lines = _read_text(self.file).splitlines()

        header_idx = None
        for i, line in enumerate(lines):
            low = line.lower()
            if "symbol" in low and ("qty" in low or "quantity" in low):
                header_idx = i
                break
        if header_idx is None:
            raise ValueError(
                "Could not find the E*TRADE header row (a line containing both "
                "'Symbol' and 'Qty'). Is this a portfolio export?"
            )

        acct_name = self.account or _account_name_from_preamble(lines, header_idx, "Brokerage")
        account = Account(institution="E*TRADE", name=acct_name, type="brokerage")

        # E*TRADE appends a trailing comma to its summary rows (CASH / TOTAL),
        # making them wider than the header and breaking the CSV parser. Strip
        # trailing commas + whitespace so every row matches the column count.
        data = [re.sub(r",+\s*$", "", ln) for ln in lines[header_idx:]]
        df = pd.read_csv(io.StringIO("\n".join(data)), dtype=str).fillna("")
        df.columns = [c.strip().lower() for c in df.columns]

        sym_col = _find_col(df.columns, "symbol")
        qty_col = _find_col(df.columns, "qty") or _find_col(df.columns, "quantity")
        paid_col = (
            _find_col(df.columns, "price", "paid")
            or _find_col(df.columns, "purchase", "price")
            or _find_col(df.columns, "cost")
        )
        value_col = _find_col(df.columns, "value")
        if not sym_col or not qty_col:
            raise ValueError(
                f"E*TRADE export missing Symbol/Qty columns. Found: {list(df.columns)}"
            )

        holdings: List[Holding] = []
        cash_total = 0.0
        for _, row in df.iterrows():
            symbol = str(row.get(sym_col, "")).strip()
            upper = symbol.upper()
            if not symbol or upper in TOTAL_ROW_SYMBOLS:
                continue
            if upper in CASH_ROW_SYMBOLS:
                if value_col:
                    cash_total += to_float(row.get(value_col))
                continue
            quantity = to_float(row.get(qty_col))
            if quantity == 0:
                continue  # disclaimer / zero-qty rows
            cost_per_share = to_float(row.get(paid_col)) if paid_col else 0.0
            holdings.append(
                Holding(
                    account_id=account.account_id,
                    symbol=symbol,
                    quantity=quantity,
                    cost_per_share=cost_per_share,
                    source=self.name,
                )
            )

        balances = (
            [Balance(account_id=account.account_id, balance=cash_total, source=self.name)]
            if cash_total
            else []
        )
        return ImportResult(accounts=[account], holdings=holdings, balances=balances)
