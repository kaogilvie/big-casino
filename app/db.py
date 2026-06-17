"""DuckDB store — the local source of truth.

Four tables, each a distinct entity:

  accounts   account metadata (slug id, institution, name, type, currency)
  holdings   stock positions, FK -> accounts (account_id, symbol)
  balances   cash / bank / card balances, FK -> accounts (one current per account)
  prices     latest quote per symbol, with as_of — decoupled from holdings so a
             price refresh never rewrites a position

`SCHEMA_VERSION` guards the file: if an older incompatible schema is found, the
tables are dropped and recreated (the only persisted data is your imports, which
are re-importable).
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, Iterable, List

import duckdb
import pandas as pd

from app.models import Account, Balance, Holding
from app.sources.base import parse_date

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "portfolio.duckdb")

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id   VARCHAR PRIMARY KEY,
    institution  VARCHAR NOT NULL,
    name         VARCHAR NOT NULL,
    type         VARCHAR NOT NULL DEFAULT 'brokerage',
    currency     VARCHAR NOT NULL DEFAULT 'USD',
    created_at   TIMESTAMP,
    updated_at   TIMESTAMP
);

-- One row per purchase LOT (not per symbol), so exact cost basis and per-lot
-- return are preserved. A position = the sum of its lots for (account_id, symbol).
CREATE SEQUENCE IF NOT EXISTS holdings_lot_seq START 1;
CREATE TABLE IF NOT EXISTS holdings (
    lot_id          BIGINT  DEFAULT nextval('holdings_lot_seq') PRIMARY KEY,
    account_id      VARCHAR NOT NULL,
    symbol          VARCHAR NOT NULL,
    quantity        DOUBLE  NOT NULL,
    cost_per_share  DOUBLE  NOT NULL,
    purchase_date   DATE,
    source          VARCHAR,
    imported_at     TIMESTAMP
);

CREATE TABLE IF NOT EXISTS balances (
    account_id   VARCHAR PRIMARY KEY,
    balance      DOUBLE NOT NULL,
    as_of        TIMESTAMP,
    source       VARCHAR,
    imported_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prices (
    symbol   VARCHAR PRIMARY KEY,
    price    DOUBLE NOT NULL,
    as_of    TIMESTAMP,
    source   VARCHAR
);

CREATE TABLE IF NOT EXISTS meta (
    key    VARCHAR PRIMARY KEY,
    value  VARCHAR
);
"""

_TABLES = ("accounts", "holdings", "balances", "prices", "meta")


def _existing_version(con) -> int | None:
    tables = {
        r[0]
        for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }
    if "meta" not in tables:
        # A pre-versioning DB (or empty file). Treat any pre-existing holdings as stale.
        return 0 if "holdings" in tables else None
    row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row[0]) if row else 0


def connect(db_path: str = DEFAULT_DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = duckdb.connect(db_path)
    version = _existing_version(con)
    if version is not None and version < SCHEMA_VERSION:
        for t in _TABLES:
            con.execute(f"DROP TABLE IF EXISTS {t}")
        con.execute("DROP SEQUENCE IF EXISTS holdings_lot_seq")
    con.execute(_SCHEMA)
    con.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        [str(SCHEMA_VERSION)],
    )
    return con


# ---------------------------------------------------------------- writes

def upsert_accounts(con, accounts: Iterable[Account]) -> int:
    now = datetime.now()
    rows = [
        (a.account_id, a.institution, a.name, a.type, a.currency, now, now)
        for a in accounts
    ]
    if not rows:
        return 0
    con.executemany(
        """
        INSERT INTO accounts (account_id, institution, name, type, currency, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (account_id) DO UPDATE SET
            institution = excluded.institution,
            name        = excluded.name,
            type        = excluded.type,
            currency    = excluded.currency,
            updated_at  = excluded.updated_at
        """,
        rows,
    )
    return len(rows)


def replace_holdings(con, account_ids: Iterable[str], holdings: Iterable[Holding]) -> int:
    """Replace all lots for the given accounts with `holdings`.

    Lots are append-style records (multiple per symbol), so we can't upsert by
    symbol. Instead, an import/save is authoritative for the accounts it touches:
    clear those accounts' lots, then insert the new set. Other accounts are left
    untouched.
    """
    account_ids = sorted(set(account_ids))
    if account_ids:
        placeholders = ",".join(["?"] * len(account_ids))
        con.execute(
            f"DELETE FROM holdings WHERE account_id IN ({placeholders})", account_ids
        )

    now = datetime.now()
    rows = []
    for h in holdings:
        pdate = parse_date(h.purchase_date) if h.purchase_date else None
        rows.append(
            (h.account_id, h.symbol, float(h.quantity), float(h.cost_per_share),
             pdate, h.source, now)
        )
    if rows:
        con.executemany(
            """
            INSERT INTO holdings
                (account_id, symbol, quantity, cost_per_share, purchase_date, source, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def upsert_balances(con, balances: Iterable[Balance]) -> int:
    now = datetime.now()
    rows = [(b.account_id, float(b.balance), now, b.source, now) for b in balances]
    if not rows:
        return 0
    con.executemany(
        """
        INSERT INTO balances (account_id, balance, as_of, source, imported_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (account_id) DO UPDATE SET
            balance     = excluded.balance,
            as_of       = excluded.as_of,
            source      = excluded.source,
            imported_at = excluded.imported_at
        """,
        rows,
    )
    return len(rows)


def upsert_prices(con, prices: Dict[str, float], source: str = "yfinance") -> int:
    now = datetime.now()
    rows = [(sym.upper(), float(p), now, source) for sym, p in prices.items()]
    if not rows:
        return 0
    con.executemany(
        """
        INSERT INTO prices (symbol, price, as_of, source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (symbol) DO UPDATE SET
            price  = excluded.price,
            as_of  = excluded.as_of,
            source = excluded.source
        """,
        rows,
    )
    return len(rows)


# ---------------------------------------------------------------- reads

def load_accounts_df(con) -> pd.DataFrame:
    return con.execute(
        "SELECT account_id, institution, name, type, currency FROM accounts "
        "ORDER BY institution, name"
    ).df()


def load_holdings_df(con) -> pd.DataFrame:
    return con.execute(
        "SELECT lot_id, account_id, symbol, quantity, cost_per_share, purchase_date, "
        "source, imported_at FROM holdings ORDER BY account_id, symbol, purchase_date"
    ).df()


def load_balances_df(con) -> pd.DataFrame:
    return con.execute(
        "SELECT account_id, balance, as_of, source FROM balances ORDER BY account_id"
    ).df()


def load_prices_map(con) -> Dict[str, float]:
    return {
        r[0]: float(r[1])
        for r in con.execute("SELECT symbol, price FROM prices").fetchall()
    }


def prices_as_of(con):
    row = con.execute("SELECT max(as_of) FROM prices").fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------- admin

def clear_all(con) -> None:
    for t in ("holdings", "balances", "accounts"):
        con.execute(f"DELETE FROM {t}")
    # prices are a cache, not user data; leave them.
