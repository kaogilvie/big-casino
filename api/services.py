"""Shared backend services for the API.

Holds the single DuckDB connection (local, single-user) behind a lock, plus the
persist/price helpers that were previously inline in the Streamlit entry point.
Nothing here imports FastAPI — pure data logic over the existing `app` package.
"""
from __future__ import annotations

import threading

import pandas as pd

from app import db
from app.prices import fetch_prices

# DuckDB allows one read-write connection per process; serialize access with a
# lock since FastAPI may dispatch requests on a threadpool.
_con = None
_lock = threading.RLock()


def get_con():
    global _con
    if _con is None:
        _con = db.connect()
    return _con


class locked:
    """Context manager: hold the DB lock for a unit of work."""
    def __enter__(self):
        _lock.acquire()
        return get_con()

    def __exit__(self, *exc):
        _lock.release()
        return False


def ensure_prices(con, symbols) -> dict:
    """Return a {symbol: price} map, fetching+persisting any we don't have yet."""
    have = db.load_prices_map(con)
    wanted = {str(s).upper() for s in symbols}
    missing = sorted(wanted - set(have))
    if missing:
        fetched = fetch_prices(missing)
        if fetched:
            db.upsert_prices(con, fetched)
            have.update(fetched)
    return have


def persist(con, result) -> str:
    """Authoritative save: replace holdings for touched accounts, upsert the rest."""
    db.upsert_accounts(con, result.accounts)
    account_ids = {a.account_id for a in result.accounts} | {
        h.account_id for h in result.holdings
    }
    db.replace_holdings(con, account_ids, result.holdings)
    db.upsert_balances(con, result.balances)
    if getattr(result, "cards", None):
        db.upsert_card_details(con, result.cards)
    return result.summary()


def persist_append(con, result) -> str:
    """Additive save for manual entry: append lots, add to balances."""
    db.upsert_accounts(con, result.accounts)
    db.append_holdings(con, result.holdings)
    db.add_balances(con, result.balances)
    return result.summary()
