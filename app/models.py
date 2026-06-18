"""Normalized data contract shared by every source adapter.

Three first-class entities, each its own object (and its own DuckDB table):

  * Account  — an account at an institution (brokerage, bank, credit card, ...).
               Pure metadata; has no money on it directly.
  * Holding  — a stock/ETF position *within* an account. Investment accounts only.
  * Balance  — an uninvested cash / bank / card balance *for* an account.

Adapters (CSV today; API/Plaid later) convert their native format into an
`ImportResult` bundling these. Holdings and balances reference an account by its
slug `account_id` rather than embedding institution/name strings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# Sentinel symbol an adapter may see for an uninvested cash line. It is NOT a
# holding — adapters route it into a Balance instead.
CASH_SYMBOL = "CASH"

# Account types. Liabilities (e.g. credit cards) are netted out, not added.
ACCOUNT_TYPES = ("brokerage", "bank", "credit_card", "retirement")
LIABILITY_TYPES = ("credit_card",)


def make_account_id(institution: str, name: str) -> str:
    """Stable, human-readable slug, e.g. ('E*TRADE', 'Individual') -> 'e_trade__individual'.

    Each part is slugified independently, then joined with '__' so the
    institution/name boundary stays visible.
    """
    def _slug(s: str, fallback: str) -> str:
        out = re.sub(r"[^a-z0-9]+", "_", (s or fallback).strip().lower()).strip("_")
        return out or fallback

    return f"{_slug(institution, 'unknown')}__{_slug(name, 'default')}"


@dataclass
class Account:
    institution: str
    name: str
    type: str = "brokerage"
    currency: str = "USD"

    def __post_init__(self) -> None:
        self.institution = (self.institution or "unknown").strip()
        self.name = (self.name or "default").strip()
        self.type = (self.type or "brokerage").strip().lower()
        if self.type not in ACCOUNT_TYPES:
            self.type = "brokerage"

    @property
    def account_id(self) -> str:
        return make_account_id(self.institution, self.name)

    @property
    def is_liability(self) -> bool:
        return self.type in LIABILITY_TYPES


COST_BASIS_TYPES = ("lot", "blended")

@dataclass
class Holding:
    account_id: str
    symbol: str
    quantity: float
    cost_per_share: float
    purchase_date: Optional[str] = None  # ISO 'YYYY-MM-DD' or None
    source: str = "csv"
    cost_basis_type: str = "lot"  # "lot" = individual purchase; "blended" = averaged position

    def __post_init__(self) -> None:
        self.symbol = (self.symbol or "").strip().upper()

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.cost_per_share


@dataclass
class Balance:
    account_id: str
    balance: float
    source: str = "csv"


@dataclass
class CardDetail:
    """Credit-card statement detail for a credit_card account.

    `statement_balance` is the amount to pay by `due_date` to avoid interest
    (the last statement balance, assuming a grace period and no carried balance).
    Dates are ISO 'YYYY-MM-DD' strings or None.
    """
    account_id: str
    statement_balance: Optional[float] = None
    statement_date: Optional[str] = None
    due_date: Optional[str] = None
    minimum_payment: Optional[float] = None
    source: str = "plaid"


@dataclass
class ImportResult:
    accounts: List[Account] = field(default_factory=list)
    holdings: List[Holding] = field(default_factory=list)
    balances: List[Balance] = field(default_factory=list)
    cards: List[CardDetail] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{len(self.accounts)} account(s), "
            f"{len(self.holdings)} holding(s), "
            f"{len(self.balances)} balance(s)"
        )
