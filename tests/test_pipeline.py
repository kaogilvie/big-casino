"""Offline tests for the data pipeline (no network, no Streamlit).

Run from the project root:  python -m pytest -q   (or: python tests/test_pipeline.py)
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from app import db
from app.analytics import balances_with_accounts, enrich, totals
from app.models import Holding, make_account_id
from app.sources.etrade_csv import EtradeCSVSource
from app.sources.normalized_csv import NormalizedCSVSource, parse_normalized_df

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")


def test_account_slug():
    assert make_account_id("E*TRADE", "Individual") == "e_trade__individual"
    assert make_account_id("Robinhood", "Roth IRA") == "robinhood__roth_ira"


def test_normalized_csv_routes_cash_to_balance():
    res = NormalizedCSVSource(os.path.join(SAMPLES, "normalized_sample.csv")).fetch()
    syms = {h.symbol for h in res.holdings}
    assert syms == {"TSLA", "VOO", "AMZN"}  # CASH is NOT a holding
    assert "CASH" not in syms

    rh_id = make_account_id("robinhood", "Individual")
    cash = {b.account_id: b.balance for b in res.balances}
    assert cash[rh_id] == 2200.0  # the CASH row became a balance
    assert any(a.account_id == rh_id for a in res.accounts)


def test_etrade_csv_holdings_and_cash_balance():
    res = EtradeCSVSource(os.path.join(SAMPLES, "etrade_sample.csv")).fetch()
    syms = {h.symbol for h in res.holdings}
    assert syms == {"AAPL", "MSFT", "NVDA"}
    assert len(res.accounts) == 1
    acct = res.accounts[0]
    assert acct.institution == "E*TRADE"
    # 'CASH & CASH ALTERNATIVES' value row -> a balance
    assert res.balances and res.balances[0].balance == 3200.0
    assert res.balances[0].account_id == acct.account_id


def test_enrich_and_totals_with_cash_and_liability():
    accounts = pd.DataFrame(
        [
            {"account_id": "etrade__ind", "institution": "E*TRADE", "name": "Ind", "type": "brokerage"},
            {"account_id": "chase__check", "institution": "Chase", "name": "Check", "type": "bank"},
            {"account_id": "citi__card", "institution": "Citi", "name": "Card", "type": "credit_card"},
        ]
    )
    holdings = pd.DataFrame(
        [{"account_id": "etrade__ind", "symbol": "AAPL", "quantity": 10, "cost_per_share": 100.0}]
    )
    balances = pd.DataFrame(
        [
            {"account_id": "chase__check", "balance": 5000.0},
            {"account_id": "citi__card", "balance": 1200.0},  # liability
        ]
    )
    enriched = enrich(holdings, accounts, {"AAPL": 150.0})
    bview = balances_with_accounts(balances, accounts)
    t = totals(enriched, bview)

    assert t["investments"] == 1500.0
    assert t["unrealized"] == 500.0
    assert t["cash"] == 5000.0           # bank only
    assert t["liabilities"] == 1200.0    # credit card netted out
    assert t["net_worth"] == 1500.0 + 5000.0 - 1200.0
    print("enrich/totals: OK", t)


def _accounts_of(holdings):
    return {h.account_id for h in holdings}


def test_multiple_lots_per_symbol_preserved():
    """Two purchases of the same stock are kept as separate lots, not collapsed."""
    df = pd.DataFrame(
        [
            {"broker": "rh", "account": "Ind", "symbol": "AAPL", "quantity": 10, "cost_per_share": 120.0, "purchase_date": "2022-01-15"},
            {"broker": "rh", "account": "Ind", "symbol": "AAPL", "quantity": 5, "cost_per_share": 150.0, "purchase_date": "2023-06-01"},
        ]
    )
    res = parse_normalized_df(df)
    assert len(res.holdings) == 2  # both lots survive

    path = os.path.join(tempfile.mkdtemp(), "t.duckdb")
    con = db.connect(path)
    db.upsert_accounts(con, res.accounts)
    db.replace_holdings(con, _accounts_of(res.holdings), res.holdings)

    h = db.load_holdings_df(con)
    aapl = h[h["symbol"] == "AAPL"]
    assert len(aapl) == 2
    # Exact cost basis = 10*120 + 5*150 = 1950 (not 15 * blended avg rounding loss)
    cost_basis = float((aapl["quantity"] * aapl["cost_per_share"]).sum())
    assert cost_basis == 1950.0
    con.close()
    print("lots preserved: OK", len(aapl), "AAPL lots, cost basis", cost_basis)


def test_replace_holdings_is_per_account():
    path = os.path.join(tempfile.mkdtemp(), "t.duckdb")
    con = db.connect(path)
    res = NormalizedCSVSource(os.path.join(SAMPLES, "normalized_sample.csv")).fetch()
    db.upsert_accounts(con, res.accounts)
    db.replace_holdings(con, _accounts_of(res.holdings), res.holdings)
    db.upsert_balances(con, res.balances)

    h1 = db.load_holdings_df(con)
    assert len(h1) == len(res.holdings)

    # Re-import the same account -> replaces its lots (no duplication, idempotent).
    db.replace_holdings(con, _accounts_of(res.holdings), res.holdings)
    h2 = db.load_holdings_df(con)
    assert len(h2) == len(h1)

    # A different account's lots are untouched by a replace scoped elsewhere.
    other = [Holding(account_id="etrade__x", symbol="NVDA", quantity=3, cost_per_share=90.0)]
    db.replace_holdings(con, {"etrade__x"}, other)
    h3 = db.load_holdings_df(con)
    assert len(h3) == len(h1) + 1  # robinhood lots intact + 1 new

    # Prices persist independently.
    db.upsert_prices(con, {"TSLA": 250.0})
    assert db.load_prices_map(con)["TSLA"] == 250.0
    con.close()
    print("replace per account: OK", len(h3), "lots")


if __name__ == "__main__":
    test_account_slug()
    test_normalized_csv_routes_cash_to_balance()
    test_etrade_csv_holdings_and_cash_balance()
    test_enrich_and_totals_with_cash_and_liability()
    test_multiple_lots_per_symbol_preserved()
    test_replace_holdings_is_per_account()
    print("\nAll pipeline tests passed.")
