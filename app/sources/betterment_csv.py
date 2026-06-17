"""Betterment holdings-CSV parser -> ImportResult.

Accepts a CSV with columns: goal, account_type, symbol, shares[, cost_basis]

  goal          Betterment goal name  →  account name (e.g. "Safety Net")
  account_type  Betterment type       →  our type:
                  taxable             →  brokerage
                  roth_ira            →  retirement
                  traditional_ira     →  retirement
  symbol        ETF ticker, or CASH for uninvested cash
  shares        quantity held (fractional OK)
  cost_basis    optional total cost basis; cost_per_share = cost_basis / shares

When Plaid integration is added, implement BettermentPlaidSource with the same
fetch() signature — the store and UI need no changes.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict

import pandas as pd

from app.models import Account, Balance, Holding, ImportResult
from app.sources.base import PortfolioSource, to_float

INSTITUTION = "Betterment"

_TYPE_MAP = {
    "taxable":         "brokerage",
    "roth_ira":        "retirement",
    "traditional_ira": "retirement",
    "ira":             "retirement",
}

REQUIRED = {"goal", "account_type", "symbol", "shares"}


class BettermentCSVSource(PortfolioSource):
    name = "betterment_csv"

    def __init__(self, file):
        self.file = file

    def fetch(self) -> ImportResult:
        df = pd.read_csv(self.file, dtype=str).fillna("")
        df.columns = [c.strip().lower() for c in df.columns]

        missing = REQUIRED - set(df.columns)
        if missing:
            raise ValueError(
                f"Betterment CSV missing required column(s): {sorted(missing)}. "
                f"Expected: goal, account_type, symbol, shares[, cost_basis]"
            )

        accounts: Dict[str, Account] = {}
        holdings = []
        cash_by_account: Dict[str, float] = defaultdict(float)

        for _, row in df.iterrows():
            goal        = row["goal"].strip()
            acct_type   = _TYPE_MAP.get(row["account_type"].strip().lower(), "brokerage")
            symbol      = row["symbol"].strip().upper()
            if not goal or not symbol:
                continue

            account = Account(institution=INSTITUTION, name=goal, type=acct_type)
            accounts.setdefault(account.account_id, account)

            shares = to_float(row["shares"])

            if symbol == "CASH":
                cash_by_account[account.account_id] += shares
                continue

            cost_basis_raw = row.get("cost_basis", "").strip()
            total_cost = to_float(cost_basis_raw) if cost_basis_raw else 0.0
            cost_per_share = (total_cost / shares) if shares and total_cost else 0.0

            holdings.append(
                Holding(
                    account_id=account.account_id,
                    symbol=symbol,
                    quantity=shares,
                    cost_per_share=cost_per_share,
                    source=self.name,
                    cost_basis_type="blended",
                )
            )

        balances = [
            Balance(account_id=acct_id, balance=amount, source=self.name)
            for acct_id, amount in cash_by_account.items()
        ]
        return ImportResult(
            accounts=list(accounts.values()),
            holdings=holdings,
            balances=balances,
        )
