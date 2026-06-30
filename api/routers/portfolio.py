"""Read endpoints: the data that powers the dashboard.

GET /api/portfolio?include_retirement=bool
    One call returning summary totals, per-account rollup, holdings, balances,
    and credit-card detail — everything the frontend needs to render.
"""
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Query

from app import db
from app.analytics import balances_with_accounts, enrich, totals
from api import services
from api.serializers import records

router = APIRouter(prefix="/api", tags=["portfolio"])


def _account_rollup(enriched: pd.DataFrame, balances: pd.DataFrame) -> pd.DataFrame:
    """One row per account: holdings value + cash balance + total."""
    if not enriched.empty:
        hv = (
            enriched.groupby("account_id", sort=False)
            .agg(
                institution=("institution", "first"),
                name=("name", "first"),
                type=("type", "first"),
                holdings_value=("market_value", "sum"),
            )
            .reset_index()
        )
    else:
        hv = pd.DataFrame(
            columns=["account_id", "institution", "name", "type", "holdings_value"]
        )

    cash = (
        balances[["account_id", "balance"]].copy()
        if not balances.empty
        else pd.DataFrame(columns=["account_id", "balance"])
    )

    if not hv.empty and not cash.empty:
        table = hv.merge(cash, on="account_id", how="outer")
    elif not hv.empty:
        table = hv.copy()
        table["balance"] = 0.0
    elif not cash.empty:
        meta = [c for c in ["institution", "name", "type"] if c in balances.columns]
        table = balances[["account_id", "balance"] + meta].copy()
        table["holdings_value"] = 0.0
    else:
        return pd.DataFrame()

    if not balances.empty and "institution" in balances.columns:
        bal_meta = balances[
            ["account_id"]
            + [c for c in ["institution", "name", "type"] if c in balances.columns]
        ].set_index("account_id")
        for col in ["institution", "name", "type"]:
            if col in bal_meta.columns and col in table.columns:
                mask = table[col].isna()
                if mask.any():
                    table.loc[mask, col] = table.loc[mask, "account_id"].map(
                        bal_meta[col]
                    )

    table["holdings_value"] = table["holdings_value"].fillna(0.0)
    table["balance"] = table["balance"].fillna(0.0)
    table["total_value"] = table["holdings_value"] + table["balance"]
    return table.sort_values("total_value", ascending=False).reset_index(drop=True)


def _merge_settings(df: pd.DataFrame, settings: pd.DataFrame) -> pd.DataFrame:
    """Attach excluded/category/tax_reserved to a df keyed by account_id (defaults when unset)."""
    if df.empty:
        return df
    if settings.empty:
        df = df.copy()
        df["excluded"] = False
        df["category"] = "personal"
        return df
    out = df.merge(settings, on="account_id", how="left")
    out["excluded"] = out["excluded"].fillna(False).astype(bool)
    out["category"] = out["category"].fillna("personal")
    return out


@router.get("/portfolio")
def get_portfolio(
    include_retirement: bool = Query(True),
    category: str = Query("all"),  # "all" | "personal" | "ko"
    hide_taxes: bool = Query(False),
):
    with services.locked() as con:
        accounts_df = db.load_accounts_df(con)
        holdings_df = db.load_holdings_df(con)
        balances_df = db.load_balances_df(con)
        cards_df = db.load_card_details_df(con)
        settings_df = db.load_account_settings_df(con)

        prices = (
            services.ensure_prices(con, holdings_df["symbol"].unique())
            if not holdings_df.empty
            else {}
        )
        as_of = db.prices_as_of(con)
        plaid_last_refresh = db.get_plaid_last_refresh(con)

    enriched = _merge_settings(enrich(holdings_df, accounts_df, prices), settings_df)
    balances_v = _merge_settings(balances_with_accounts(balances_df, accounts_df), settings_df)

    # Drop excluded accounts from every view (non-destructive — data stays in DB).
    if not enriched.empty:
        enriched = enriched[~enriched["excluded"]]
    if not balances_v.empty:
        balances_v = balances_v[~balances_v["excluded"]]

    # Optional category filter (&KO vs personal).
    if category in ("personal", "ko"):
        if not enriched.empty:
            enriched = enriched[enriched["category"] == category]
        if not balances_v.empty:
            balances_v = balances_v[balances_v["category"] == category]

    if not include_retirement:
        if not enriched.empty and "type" in enriched.columns:
            enriched = enriched[enriched["type"] != "retirement"]
        if not balances_v.empty and "type" in balances_v.columns:
            balances_v = balances_v[balances_v["type"] != "retirement"]

    if hide_taxes:
        if not enriched.empty and "type" in enriched.columns:
            enriched = enriched[enriched["type"] != "taxes"]
        if not balances_v.empty and "type" in balances_v.columns:
            balances_v = balances_v[balances_v["type"] != "taxes"]

    t = totals(enriched, balances_v)
    rollup = _account_rollup(enriched, balances_v)
    # Carry category/excluded onto the rollup for the management UI.
    if not rollup.empty:
        rollup = _merge_settings(rollup.drop(columns=["excluded", "category"], errors="ignore"), settings_df)

    # Credit-card view: balances of type credit_card joined to statement detail.
    cards = pd.DataFrame()
    if not balances_v.empty and "type" in balances_v.columns:
        cards = balances_v[balances_v["type"] == "credit_card"].copy()
        if not cards.empty and not cards_df.empty:
            cards = cards.merge(cards_df, on="account_id", how="left")

    return {
        "summary": t,
        "accounts": records(rollup),
        "holdings": records(enriched),
        "balances": records(balances_v),
        "cards": records(cards),
        "prices_as_of": as_of.isoformat() if as_of is not None else None,
        "plaid_last_refresh": plaid_last_refresh.isoformat() if plaid_last_refresh is not None else None,
    }
