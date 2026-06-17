#!/usr/bin/env python3
"""Seed DuckDB from real exports in data/historical/ (gitignored).

This replaces the synthetic samples/ as the load source. Every CSV in the folder
is sniffed for its format and imported:

  * normalized template      -> NormalizedCSVSource
  * E*TRADE portfolio export -> EtradeCSVSource
  * Robinhood activity        -> not supported yet (skipped with a note)

By default the DB is cleared first so the folder is authoritative. Run with the
project venv:  .venv/bin/python scripts/seed.py
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from app import db
from app.sources.etrade_csv import EtradeCSVSource
from app.sources.normalized_csv import NormalizedCSVSource


def detect(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        head = fh.read(8192)
    low = head.lower()
    for line in head.splitlines():
        cols = {c.strip().lower() for c in line.split(",")}
        if {"broker", "account", "symbol", "quantity"} <= cols:
            return "normalized"
    if "symbol" in low and ("price paid" in low or "account summary" in low):
        return "etrade"
    if "trans code" in low or "activity date" in low:
        return "robinhood_activity"
    return "unknown"


def persist(con, result) -> str:
    db.upsert_accounts(con, result.accounts)
    account_ids = {a.account_id for a in result.accounts} | {h.account_id for h in result.holdings}
    db.replace_holdings(con, account_ids, result.holdings)
    db.upsert_balances(con, result.balances)
    return result.summary()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default="data/historical", help="folder of real exports")
    ap.add_argument("--account", default="Individual", help="account name for E*TRADE exports")
    ap.add_argument("--keep", action="store_true", help="don't clear existing data first")
    args = ap.parse_args()

    folder = os.path.join(_ROOT, args.dir)
    files = sorted(glob.glob(os.path.join(folder, "*.csv")))
    if not files:
        print(f"No CSVs found in {args.dir}/")
        return 1

    con = db.connect()
    if not args.keep:
        db.clear_all(con)

    skipped = 0
    for path in files:
        name = os.path.basename(path)
        kind = detect(path)
        try:
            if kind == "etrade":
                result = EtradeCSVSource(path, account=args.account).fetch()
            elif kind == "normalized":
                result = NormalizedCSVSource(path).fetch()
            else:
                reason = (
                    "Robinhood activity parser not built yet"
                    if kind == "robinhood_activity"
                    else "unrecognized format"
                )
                print(f"SKIP  {name}  ({reason})")
                skipped += 1
                continue
            print(f"LOAD  {name}  [{kind}]  ->  {persist(con, result)}")
        except Exception as exc:
            print(f"ERROR {name}: {exc}")
            skipped += 1

    holdings = db.load_holdings_df(con)
    accounts = db.load_accounts_df(con)
    balances = db.load_balances_df(con)
    con.close()
    print(
        f"\nDB now has {len(accounts)} account(s), {len(holdings)} lot(s), "
        f"{len(balances)} balance(s). {skipped} file(s) skipped."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
