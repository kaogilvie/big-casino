"""Canonical normalized-template loader + shared row parser.

Columns: broker, account, symbol, quantity, cost_per_share[, total_cost, type,
purchase_date]. This is the hand-entry format (CSV upload or the in-app editor)
and the format the E*TRADE parser converts into.

Routing:
  * symbol == CASH   -> a Balance for that account (summed if repeated)
  * any other symbol -> a Holding in that account
Every row's (broker, account) defines/updates an Account.

`parse_normalized_df` is the single source of truth — both the CSV source and the
manual editor call it so they behave identically.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict

import pandas as pd

from app.models import CASH_SYMBOL, Account, Balance, Holding, ImportResult
from app.sources.base import PortfolioSource, parse_date, to_float

REQUIRED = {"broker", "account", "symbol", "quantity"}


def parse_normalized_df(df: pd.DataFrame) -> ImportResult:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError(
            "Normalized data is missing required column(s): "
            f"{sorted(missing)}. Expected at least {sorted(REQUIRED)}."
        )

    df = df.fillna("")  # blank/NaN editor cells -> "" so empty rows are skipped

    accounts: Dict[str, Account] = {}
    holdings = []
    cash_by_account: Dict[str, float] = defaultdict(float)

    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol:
            continue

        account = Account(
            institution=str(row.get("broker", "")).strip(),
            name=str(row.get("account", "")).strip(),
            type=str(row.get("type", "") or "brokerage"),
        )
        accounts.setdefault(account.account_id, account)

        quantity = to_float(row.get("quantity"))

        if symbol == CASH_SYMBOL:
            cash_by_account[account.account_id] += quantity
            continue

        cps_raw = str(row.get("cost_per_share", "")).strip()
        total_raw = str(row.get("total_cost", "")).strip()
        if cps_raw:
            cost_per_share = to_float(cps_raw)
        elif total_raw and quantity:
            cost_per_share = to_float(total_raw) / quantity
        else:
            cost_per_share = 0.0

        holdings.append(
            Holding(
                account_id=account.account_id,
                symbol=symbol,
                quantity=quantity,
                cost_per_share=cost_per_share,
                purchase_date=parse_date(row.get("purchase_date")),
                source="normalized",
            )
        )

    balances = [
        Balance(account_id=acct_id, balance=amount, source="normalized")
        for acct_id, amount in cash_by_account.items()
    ]
    return ImportResult(
        accounts=list(accounts.values()), holdings=holdings, balances=balances
    )


class NormalizedCSVSource(PortfolioSource):
    name = "normalized_csv"

    def __init__(self, file):
        # `file` may be a path or a file-like object (Streamlit upload).
        self.file = file

    def fetch(self) -> ImportResult:
        df = pd.read_csv(self.file, dtype=str)
        return parse_normalized_df(df)
