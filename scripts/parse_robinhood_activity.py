#!/usr/bin/env python3
"""Parse Robinhood account activity CSVs into a normalized lots CSV.

Reads all CSVs in data/historical/robinhood/, extracts Buy rows, handles
known corporate actions, and writes data/historical/robinhood_lots.csv in
the normalized template format (broker, account, type, symbol, quantity,
cost_per_share, purchase_date).

Run from the project root:  .venv/bin/python scripts/parse_robinhood_activity.py
"""
from __future__ import annotations

import csv
import glob
import os
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ------------------------------------------------------------------ corp actions

# These symbols are fully excluded — their lots were wiped out by corporate events.
_EXCLUDE_SYMBOLS = {
    "BOWX":  "converted to WE via SPAC merger (Oct 2021) → WE went bankrupt → written off",
    "WE":    "went bankrupt; shares spun off to WEWKQ (Sep 2023) → written off",
    "WEWKQ": "received in WE bankruptcy; written off (Jun 2024)",
}

# Old SIX lots were converted to FUN shares in the Cedar Fair/Six Flags merger (Jul 2024).
# Any SIX Buy before this date gets replaced by the synthetic FUN lot below.
_SIX_MERGER_DATE = "2024-07-02"
_SIX_TOTAL_COST  = 430.40   # 20 shares @ $21.52 (the one SIX buy on 2023-11-02)
_FUN_SHARES      = 11.6     # shares of FUN received in the merger


# ------------------------------------------------------------------ helpers

def _parse_price(s: str) -> float:
    """'$51.50' or '($3.97)' -> float (negative if parenthesised)."""
    s = s.strip().lstrip("$").replace(",", "")
    negative = s.startswith("(") and s.endswith(")")
    val = float(s.strip("()")) if s.strip("()") else 0.0
    return -val if negative else val


def _parse_date(s: str) -> str:
    """'12/7/2021' -> '2021-12-07'"""
    return datetime.strptime(s.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")


def _read_file(path: str) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            date = (row.get("Activity Date") or "").strip()
            trans = (row.get("Trans Code") or "").strip()
            # skip blank rows and the disclaimer footer
            if not date or not trans:
                continue
            rows.append(row)
    return rows


# ------------------------------------------------------------------ main

def main() -> int:
    rh_dir = os.path.join(_ROOT, "data", "historical", "robinhood")
    files  = sorted(glob.glob(os.path.join(rh_dir, "*.csv")))
    if not files:
        print(f"No CSVs found in {rh_dir}")
        return 1

    all_rows: list[dict] = []
    for path in files:
        rows = _read_file(path)
        all_rows.extend(rows)
        print(f"  read {len(rows):3d} rows  {os.path.basename(path)}")

    # chronological order
    all_rows.sort(key=lambda r: datetime.strptime(r["Activity Date"].strip(), "%m/%d/%Y"))

    lots: list[dict] = []
    excluded: set[str] = set()
    six_lots_excluded = False
    warns: list[str] = []

    for row in all_rows:
        trans      = row["Trans Code"].strip()
        symbol     = row["Instrument"].strip()
        date_raw   = row["Activity Date"].strip()

        if trans != "Buy" or not symbol:
            continue

        # fully-excluded symbols
        if symbol in _EXCLUDE_SYMBOLS:
            if symbol not in excluded:
                warns.append(f"EXCLUDED  {symbol:8s}  {_EXCLUDE_SYMBOLS[symbol]}")
                excluded.add(symbol)
            continue

        # old SIX lots -> replaced by synthetic FUN lot
        if symbol == "SIX" and _parse_date(date_raw) < _SIX_MERGER_DATE:
            six_lots_excluded = True
            continue

        try:
            qty   = float(row["Quantity"].strip())
            price = _parse_price(row["Price"])
            date  = _parse_date(date_raw)
        except (ValueError, KeyError) as exc:
            warns.append(f"SKIPPED malformed row ({exc}): {dict(row)}")
            continue

        lots.append({
            "broker":          "Robinhood",
            "account":         "Individual",
            "type":            "brokerage",
            "symbol":          symbol,
            "quantity":        qty,
            "cost_per_share":  price,
            "purchase_date":   date,
        })

    # synthetic FUN lot from the Cedar Fair/Six Flags merger
    if six_lots_excluded:
        fun_cost = round(_SIX_TOTAL_COST / _FUN_SHARES, 4)
        lots.append({
            "broker":         "Robinhood",
            "account":        "Individual",
            "type":           "brokerage",
            "symbol":         "FUN",
            "quantity":       _FUN_SHARES,
            "cost_per_share": fun_cost,
            "purchase_date":  _SIX_MERGER_DATE,
        })
        warns.append(
            f"REPLACED   SIX    20 shares with synthetic FUN {_FUN_SHARES} shares "
            f"@ ${fun_cost} (cost basis carried: ${_SIX_TOTAL_COST:.2f} / {_FUN_SHARES} shares)"
        )

    lots.sort(key=lambda r: r["purchase_date"])

    out_path = os.path.join(_ROOT, "data", "historical", "robinhood_lots.csv")
    with open(out_path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["broker", "account", "type", "symbol", "quantity", "cost_per_share", "purchase_date"],
        )
        writer.writeheader()
        writer.writerows(lots)

    print(f"\nWrote {len(lots)} lots -> {os.path.relpath(out_path, _ROOT)}")
    if warns:
        print("\nNotes:")
        for w in warns:
            print(f"  {w}")

    # show a summary grouped by symbol so you can spot anything odd
    from collections import defaultdict
    by_sym: dict[str, float] = defaultdict(float)
    for lot in lots:
        by_sym[lot["symbol"]] += lot["quantity"]

    print("\nTotal shares per symbol after adjustments:")
    for sym, qty in sorted(by_sym.items()):
        print(f"  {sym:8s}  {qty:.6g}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
