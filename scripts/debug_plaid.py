"""Dump raw Plaid account data for all stored items.

Usage:
    python scripts/debug_plaid.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, plaid_client as plaid_cfg
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest

import duckdb
con = duckdb.connect(db.DEFAULT_DB_PATH, read_only=True)
items = db.load_plaid_items(con)

if items.empty:
    print("No Plaid items found.")
    sys.exit(0)

client = plaid_cfg.get_client()

for _, row in items.iterrows():
    print(f"\n{'='*60}")
    print(f"Institution : {row['institution']}")
    print(f"Item ID     : {row['item_id']}")
    print(f"Connected   : {row['created_at']}")
    print()

    token = db.get_plaid_access_token(con, row["item_id"])
    resp = client.accounts_balance_get(AccountsBalanceGetRequest(access_token=token))

    # account_id -> name, for labeling holdings below
    acct_names = {}
    for acct in resp["accounts"]:
        acct_names[acct.get("account_id")] = acct.get("name")
        bal = acct.get("balances", {})
        print(f"  Name            : {acct.get('name')}")
        print(f"  Official name   : {acct.get('official_name')}")
        print(f"  Type            : {acct.get('type')}")
        print(f"  Subtype         : {acct.get('subtype')}")
        print(f"  Account ID      : {acct.get('account_id')}")
        print(f"  Balance current : {bal.get('current')}")
        print(f"  Balance avail   : {bal.get('available')}")
        print()

    # ── Investments holdings (verify cost_basis semantics) ────────────
    try:
        inv = client.investments_holdings_get(
            InvestmentsHoldingsGetRequest(access_token=token)
        )
    except Exception as exc:
        print(f"  [no investments product for this item: {exc}]")
        continue

    secs = {s["security_id"]: s for s in inv["securities"]}
    print(f"\n  --- HOLDINGS ({len(inv['holdings'])}) ---")
    for h in inv["holdings"]:
        sec = secs.get(h["security_id"], {})
        qty = h.get("quantity") or 0
        cost_basis = h.get("cost_basis")
        per_share = (float(cost_basis) / qty) if (cost_basis and qty) else None
        print(f"    {acct_names.get(h['account_id'], '?')}")
        print(f"      ticker        : {sec.get('ticker_symbol')}")
        print(f"      sec name      : {sec.get('name')}")
        print(f"      sec type      : {sec.get('type')}")
        print(f"      quantity      : {qty}")
        print(f"      inst price    : {h.get('institution_price')}")
        print(f"      inst value    : {h.get('institution_value')}")
        print(f"      cost_basis    : {cost_basis}  (=> per-share {per_share})")
        print()
