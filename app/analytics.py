"""Derive the live financial view from raw entities + a price map.

Pure functions over DataFrames so they're easy to unit-test without Streamlit or
a network. Holdings are joined to their account (for labels/grouping) and to
prices (for market value); balances (cash) and account types feed the net-worth
roll-up. Nothing here mutates the stored data.
"""
from __future__ import annotations

from typing import Dict

import pandas as pd

from app.models import LIABILITY_TYPES

ENRICHED_COLUMNS = [
    "current_price",
    "cost_basis",
    "market_value",
    "unrealized",
    "unrealized_pct",
]


def enrich(holdings: pd.DataFrame, accounts: pd.DataFrame, prices: Dict[str, float]) -> pd.DataFrame:
    """Holdings + account metadata + live price -> per-position market view."""
    out = holdings.copy()

    if not accounts.empty:
        out = out.merge(
            accounts[["account_id", "institution", "name", "type"]],
            on="account_id",
            how="left",
        )
    else:
        out["institution"] = None
        out["name"] = None
        out["type"] = None

    if out.empty:
        for col in ENRICHED_COLUMNS:
            out[col] = pd.Series(dtype="float64")
        return out

    out["current_price"] = out["symbol"].map(lambda s: prices.get(str(s).upper()))
    out["cost_basis"] = out["quantity"] * out["cost_per_share"]
    out["market_value"] = out["quantity"] * out["current_price"]
    out["unrealized"] = out["market_value"] - out["cost_basis"]
    out["unrealized_pct"] = out.apply(
        lambda r: (r["unrealized"] / r["cost_basis"] * 100.0)
        if r["cost_basis"] not in (0, None) and pd.notna(r["market_value"])
        else None,
        axis=1,
    )
    return out


def balances_with_accounts(balances: pd.DataFrame, accounts: pd.DataFrame) -> pd.DataFrame:
    if balances.empty:
        return balances.assign(institution=None, name=None, type=None)
    if accounts.empty:
        return balances.assign(institution=None, name=None, type="brokerage")
    return balances.merge(
        accounts[["account_id", "institution", "name", "type"]],
        on="account_id",
        how="left",
    )


def totals(enriched_holdings: pd.DataFrame, balances: pd.DataFrame) -> Dict[str, float]:
    """Roll up investments, cash, net worth and unrealized return.

    Liability accounts (e.g. credit cards) subtract from net worth; their cash
    balance is treated as the amount owed.
    """
    investments = (
        float(enriched_holdings["market_value"].sum(skipna=True))
        if not enriched_holdings.empty
        else 0.0
    )
    cost_basis = (
        float(enriched_holdings["cost_basis"].sum(skipna=True))
        if not enriched_holdings.empty
        else 0.0
    )
    unrealized = investments - cost_basis
    unrealized_pct = (unrealized / cost_basis * 100.0) if cost_basis else 0.0

    cash = 0.0
    liabilities = 0.0
    if not balances.empty:
        bt = balances.copy()
        if "type" not in bt.columns:
            bt["type"] = "brokerage"
        is_liab = bt["type"].isin(LIABILITY_TYPES)
        cash = float(bt.loc[~is_liab, "balance"].sum())
        liabilities = float(bt.loc[is_liab, "balance"].sum())

    net_worth = investments + cash - liabilities
    return {
        "investments": investments,
        "cost_basis": cost_basis,
        "unrealized": unrealized,
        "unrealized_pct": unrealized_pct,
        "cash": cash,
        "liabilities": liabilities,
        "net_worth": net_worth,
    }
