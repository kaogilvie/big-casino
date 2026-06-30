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

from app.models import Account, Balance, CardDetail, Holding
from app.sources.base import parse_date

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "portfolio.duckdb")

SCHEMA_VERSION = 4

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id   VARCHAR PRIMARY KEY,
    institution  VARCHAR NOT NULL,
    name         VARCHAR NOT NULL,
    type         VARCHAR NOT NULL DEFAULT 'brokerage',
    currency     VARCHAR NOT NULL DEFAULT 'USD',
    item_id      VARCHAR,          -- Plaid item this account came from (NULL for manual/file)
    created_at   TIMESTAMP,
    updated_at   TIMESTAMP
);
-- For DBs created before `item_id` existed.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS item_id VARCHAR;

-- One row per purchase LOT (not per symbol), so exact cost basis and per-lot
-- return are preserved. A position = the sum of its lots for (account_id, symbol).
CREATE SEQUENCE IF NOT EXISTS holdings_lot_seq START 1;
CREATE TABLE IF NOT EXISTS holdings (
    lot_id           BIGINT  DEFAULT nextval('holdings_lot_seq') PRIMARY KEY,
    account_id       VARCHAR NOT NULL,
    symbol           VARCHAR NOT NULL,
    quantity         DOUBLE  NOT NULL,
    cost_per_share   DOUBLE  NOT NULL,
    purchase_date    DATE,
    cost_basis_type  VARCHAR NOT NULL DEFAULT 'lot',
    source           VARCHAR,
    imported_at      TIMESTAMP
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

_PLAID_SCHEMA = """
CREATE TABLE IF NOT EXISTS plaid_items (
    item_id      VARCHAR PRIMARY KEY,
    access_token VARCHAR NOT NULL,
    institution  VARCHAR,
    alias        VARCHAR,
    created_at   TIMESTAMP
);
-- For DBs created before `alias` existed (table isn't dropped on version bumps).
ALTER TABLE plaid_items ADD COLUMN IF NOT EXISTS alias VARCHAR;
"""

_CARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS card_details (
    account_id        VARCHAR PRIMARY KEY,
    statement_balance DOUBLE,
    statement_date    DATE,
    due_date          DATE,
    minimum_payment   DOUBLE,
    source            VARCHAR,
    imported_at       TIMESTAMP
);
"""

# User preferences per account, decoupled from import-managed `accounts` so a
# Plaid/file refresh never overwrites them. category: 'personal' | 'ko'.
_ACCOUNT_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS account_settings (
    account_id  VARCHAR PRIMARY KEY,
    excluded    BOOLEAN NOT NULL DEFAULT FALSE,
    category    VARCHAR NOT NULL DEFAULT 'personal'
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
    con.execute(_PLAID_SCHEMA)
    con.execute(_CARD_SCHEMA)
    con.execute(_ACCOUNT_SETTINGS_SCHEMA)
    con.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        [str(SCHEMA_VERSION)],
    )
    # One-time: link pre-existing Plaid accounts to their item (item_id was added later).
    done = con.execute("SELECT value FROM meta WHERE key = 'item_backfill_v1'").fetchone()
    if not done:
        _backfill_item_links(con)
        con.execute(
            "INSERT INTO meta (key, value) VALUES ('item_backfill_v1', '1') "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value"
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
             pdate, h.cost_basis_type, h.source, now)
        )
    if rows:
        con.executemany(
            """
            INSERT INTO holdings
                (account_id, symbol, quantity, cost_per_share, purchase_date,
                 cost_basis_type, source, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def append_holdings(con, holdings: Iterable[Holding]) -> int:
    """Insert lots without clearing anything — additive (for manual entry).

    Unlike `replace_holdings`, this never deletes existing lots, so entering one
    new buy adds it to the account rather than wiping the rest.
    """
    now = datetime.now()
    rows = []
    for h in holdings:
        pdate = parse_date(h.purchase_date) if h.purchase_date else None
        rows.append(
            (h.account_id, h.symbol, float(h.quantity), float(h.cost_per_share),
             pdate, h.cost_basis_type, h.source, now)
        )
    if rows:
        con.executemany(
            """
            INSERT INTO holdings
                (account_id, symbol, quantity, cost_per_share, purchase_date,
                 cost_basis_type, source, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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


def add_balances(con, balances: Iterable[Balance]) -> int:
    """Add to each account's balance (create it if absent) — additive counterpart
    to `upsert_balances`, so a manual CASH entry adds cash instead of replacing it.
    """
    now = datetime.now()
    rows = [(b.account_id, float(b.balance), now, b.source, now) for b in balances]
    if not rows:
        return 0
    con.executemany(
        """
        INSERT INTO balances (account_id, balance, as_of, source, imported_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (account_id) DO UPDATE SET
            balance     = balances.balance + excluded.balance,
            as_of       = excluded.as_of,
            source      = excluded.source,
            imported_at = excluded.imported_at
        """,
        rows,
    )
    return len(rows)


def upsert_card_details(con, cards: Iterable[CardDetail]) -> int:
    now = datetime.now()
    rows = []
    for c in cards:
        rows.append((
            c.account_id,
            c.statement_balance,
            parse_date(c.statement_date) if c.statement_date else None,
            parse_date(c.due_date) if c.due_date else None,
            c.minimum_payment,
            c.source,
            now,
        ))
    if not rows:
        return 0
    con.executemany(
        """
        INSERT INTO card_details
            (account_id, statement_balance, statement_date, due_date,
             minimum_payment, source, imported_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (account_id) DO UPDATE SET
            statement_balance = excluded.statement_balance,
            statement_date    = excluded.statement_date,
            due_date          = excluded.due_date,
            minimum_payment   = excluded.minimum_payment,
            source            = excluded.source,
            imported_at       = excluded.imported_at
        """,
        rows,
    )
    return len(rows)


def load_card_details_df(con) -> pd.DataFrame:
    return con.execute(
        "SELECT account_id, statement_balance, statement_date, due_date, "
        "minimum_payment FROM card_details ORDER BY account_id"
    ).df()


def load_account_settings_df(con) -> pd.DataFrame:
    return con.execute(
        "SELECT account_id, excluded, category FROM account_settings"
    ).df()


def upsert_account_settings(con, account_id: str, excluded=None, category=None) -> None:
    """Partial update of per-account settings; unspecified fields keep their value."""
    con.execute(
        "INSERT INTO account_settings (account_id) VALUES (?) ON CONFLICT (account_id) DO NOTHING",
        [account_id],
    )
    if excluded is not None:
        con.execute(
            "UPDATE account_settings SET excluded = ? WHERE account_id = ?",
            [bool(excluded), account_id],
        )
    if category is not None:
        con.execute(
            "UPDATE account_settings SET category = ? WHERE account_id = ?",
            [category, account_id],
        )


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
        "cost_basis_type, source, imported_at FROM holdings ORDER BY account_id, symbol, purchase_date"
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


def upsert_plaid_item(con, item_id: str, access_token: str, institution: str) -> None:
    now = datetime.now()
    con.execute(
        """
        INSERT INTO plaid_items (item_id, access_token, institution, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (item_id) DO UPDATE SET
            access_token = excluded.access_token,
            institution  = excluded.institution
        """,
        [item_id, access_token, institution, now],
    )


def load_plaid_items(con) -> pd.DataFrame:
    return con.execute(
        "SELECT item_id, institution, alias, created_at FROM plaid_items ORDER BY created_at"
    ).df()


def set_plaid_alias(con, item_id: str, alias: str | None) -> None:
    con.execute(
        "UPDATE plaid_items SET alias = ? WHERE item_id = ?",
        [(alias or None), item_id],
    )


def get_plaid_item(con, item_id: str) -> dict | None:
    row = con.execute(
        "SELECT item_id, institution, alias FROM plaid_items WHERE item_id = ?", [item_id]
    ).fetchone()
    if not row:
        return None
    return {"item_id": row[0], "institution": row[1], "alias": row[2]}


def unique_institution(con, base: str) -> str:
    """Return `base`, or 'base (2)', 'base (3)'… so two same-bank Plaid logins
    don't share an account namespace."""
    existing = {
        r[0] for r in con.execute("SELECT institution FROM plaid_items").fetchall()
    }
    if base not in existing:
        return base
    n = 2
    while f"{base} ({n})" in existing:
        n += 1
    return f"{base} ({n})"


def tag_accounts_with_item(con, account_ids: Iterable[str], item_id: str) -> None:
    ids = list(account_ids)
    if not ids:
        return
    placeholders = ",".join(["?"] * len(ids))
    con.execute(
        f"UPDATE accounts SET item_id = ? WHERE account_id IN ({placeholders})",
        [item_id, *ids],
    )


def accounts_for_item(con, item_id: str) -> pd.DataFrame:
    return con.execute(
        "SELECT account_id, institution, name, type FROM accounts WHERE item_id = ?",
        [item_id],
    ).df()


def renamespace_item_accounts(con, item_id: str, new_institution: str) -> int:
    """Re-slug every account belonging to a Plaid item under a new institution
    namespace (keeps each account's name/type). Returns count re-namespaced."""
    df = accounts_for_item(con, item_id)
    count = 0
    for _, row in df.iterrows():
        if row["institution"] == new_institution:
            continue
        rename_account(con, row["account_id"], new_institution, row["name"], row["type"])
        count += 1
    return count


def _backfill_item_links(con) -> None:
    """One-time: link pre-existing Plaid accounts (imported before item_id existed)
    to their item by institution match, then align them to each item's namespace
    (alias or institution). Restricted to plaid-sourced accounts so manual/file
    accounts aren't mislinked."""
    items = con.execute("SELECT item_id, institution, alias FROM plaid_items").fetchall()
    for item_id, institution, alias in items:
        con.execute(
            """
            UPDATE accounts SET item_id = ?
            WHERE item_id IS NULL
              AND institution IN (?, ?)
              AND account_id IN (
                  SELECT account_id FROM balances WHERE source = 'plaid'
                  UNION
                  SELECT account_id FROM holdings WHERE source = 'plaid'
              )
            """,
            [item_id, institution, alias or institution],
        )
        renamespace_item_accounts(con, item_id, alias or institution)


def get_meta(con, key: str) -> str | None:
    row = con.execute("SELECT value FROM meta WHERE key = ?", [key]).fetchone()
    return row[0] if row else None


def set_meta(con, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        [key, value],
    )


def touch_plaid_refresh(con) -> None:
    """Record the current timestamp as the last time any Plaid item was refreshed."""
    set_meta(con, "plaid_last_refresh", datetime.now().isoformat())


def get_plaid_last_refresh(con) -> datetime | None:
    val = get_meta(con, "plaid_last_refresh")
    return datetime.fromisoformat(val) if val else None


def get_plaid_access_token(con, item_id: str) -> str | None:
    row = con.execute(
        "SELECT access_token FROM plaid_items WHERE item_id = ?", [item_id]
    ).fetchone()
    return row[0] if row else None


def delete_plaid_item(con, item_id: str) -> None:
    con.execute("DELETE FROM plaid_items WHERE item_id = ?", [item_id])


def delete_plaid_connection(con, item_id: str, institution: str) -> None:
    """Remove a Plaid connection: its stored creds plus the data it imported.

    Holdings/balances tagged source='plaid' under this institution's accounts are
    deleted, then any account left with no holdings and no balance is dropped.
    Manually-entered data (other sources) and other institutions are untouched.
    """
    from app.models import make_account_id

    # Accounts under this institution are slugged "<institution>__*".
    prefix = make_account_id(institution, "x").rsplit("__", 1)[0] + "__"
    like = prefix + "%"

    con.execute(
        "DELETE FROM holdings WHERE source = 'plaid' AND account_id LIKE ?", [like]
    )
    con.execute(
        "DELETE FROM balances WHERE source = 'plaid' AND account_id LIKE ?", [like]
    )
    con.execute(
        "DELETE FROM card_details WHERE account_id LIKE ?", [like]
    )
    con.execute(
        "DELETE FROM account_settings WHERE account_id LIKE ?", [like]
    )
    # Drop now-empty accounts for this institution.
    con.execute(
        """
        DELETE FROM accounts
        WHERE account_id LIKE ?
          AND account_id NOT IN (SELECT account_id FROM holdings)
          AND account_id NOT IN (SELECT account_id FROM balances)
        """,
        [like],
    )
    con.execute("DELETE FROM plaid_items WHERE item_id = ?", [item_id])


def rename_account(con, old_account_id: str, institution: str, name: str, account_type: str) -> str:
    """Rename an account, updating the slug and all FK references.

    Returns the new account_id.
    """
    from app.models import make_account_id
    new_id = make_account_id(institution, name)
    now = datetime.now()
    # Preserve the Plaid item link across the slug change.
    row = con.execute("SELECT item_id FROM accounts WHERE account_id = ?", [old_account_id]).fetchone()
    item_id = row[0] if row else None
    if new_id != old_account_id:
        con.execute(
            "UPDATE holdings SET account_id = ? WHERE account_id = ?", [new_id, old_account_id]
        )
        con.execute(
            "UPDATE balances SET account_id = ? WHERE account_id = ?", [new_id, old_account_id]
        )
        # Carry user settings + card detail across the slug change (DuckDB has no
        # UPDATE OR REPLACE, so clear any row already at the new id, then move).
        con.execute("DELETE FROM account_settings WHERE account_id = ?", [new_id])
        con.execute(
            "UPDATE account_settings SET account_id = ? WHERE account_id = ?",
            [new_id, old_account_id],
        )
        con.execute("DELETE FROM card_details WHERE account_id = ?", [new_id])
        con.execute(
            "UPDATE card_details SET account_id = ? WHERE account_id = ?",
            [new_id, old_account_id],
        )
    con.execute(
        """
        INSERT INTO accounts (account_id, institution, name, type, currency, item_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'USD', ?, ?, ?)
        ON CONFLICT (account_id) DO UPDATE SET
            institution = excluded.institution,
            name        = excluded.name,
            type        = excluded.type,
            item_id     = excluded.item_id,
            updated_at  = excluded.updated_at
        """,
        [new_id, institution, name, account_type, item_id, now, now],
    )
    if new_id != old_account_id:
        con.execute("DELETE FROM accounts WHERE account_id = ?", [old_account_id])
    return new_id


def delete_holdings(con, lot_ids: Iterable[int]) -> int:
    ids = list(lot_ids)
    if not ids:
        return 0
    placeholders = ",".join(["?"] * len(ids))
    con.execute(f"DELETE FROM holdings WHERE lot_id IN ({placeholders})", ids)
    return len(ids)


# ---------------------------------------------------------------- admin

def clear_all(con) -> None:
    for t in ("holdings", "balances", "accounts"):
        con.execute(f"DELETE FROM {t}")
    # prices are a cache, not user data; leave them.
