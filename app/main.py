"""Streamlit entry point for the personal portfolio dashboard.

Run from the project root:  streamlit run app/main.py
"""
from __future__ import annotations

import os
import sys

# Make the `app` package importable when launched via `streamlit run app/main.py`
# (Streamlit puts the script's own dir on sys.path, not the project root).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

from app import db
from app.analytics import balances_with_accounts, enrich
from app.models import ACCOUNT_TYPES
from app.prices import fetch_prices
from app.sources.etrade_csv import EtradeCSVSource
from app.sources.normalized_csv import NormalizedCSVSource, parse_normalized_df
from app.theme import apply_theme
from app.views import holdings as holdings_view
from app.views import overview as overview_view

st.set_page_config(page_title="Portfolio", page_icon="📈", layout="wide")
apply_theme(st)


@st.cache_resource
def get_connection():
    return db.connect()


@st.cache_data(ttl=900, show_spinner=False)
def cached_quotes(symbols: tuple) -> dict:
    """Network call to yfinance, memoized per symbol-set for the session."""
    return fetch_prices(list(symbols))


def ensure_prices(con, symbols) -> dict:
    """Return a {symbol: price} map, fetching+persisting any symbols we don't have yet."""
    have = db.load_prices_map(con)
    wanted = {str(s).upper() for s in symbols}
    missing = tuple(sorted(wanted - set(have)))
    if missing:
        fetched = cached_quotes(missing)
        if fetched:
            db.upsert_prices(con, fetched)
            have.update(fetched)
    return have


def persist(con, result) -> str:
    db.upsert_accounts(con, result.accounts)
    # Replace lots for every account this import touches (authoritative per account).
    account_ids = {a.account_id for a in result.accounts} | {h.account_id for h in result.holdings}
    db.replace_holdings(con, account_ids, result.holdings)
    db.upsert_balances(con, result.balances)
    return result.summary()


def do_import(con, source) -> str:
    return persist(con, source.fetch())


# Empty grid for manual entry — typed columns so the editor renders proper inputs.
_MANUAL_COLUMNS = {
    "broker": str,
    "account": str,
    "type": str,
    "symbol": str,
    "quantity": float,
    "cost_per_share": float,
    "purchase_date": str,
}


def _empty_manual_df() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in _MANUAL_COLUMNS.items()})


def _current_lots_df(con) -> pd.DataFrame:
    """Existing lots in the editor's column shape, so the grid edits real data."""
    holdings = db.load_holdings_df(con)
    accounts = db.load_accounts_df(con)
    if holdings.empty:
        return _empty_manual_df()
    m = holdings.merge(accounts, on="account_id", how="left")
    dates = m["purchase_date"].astype(str).replace({"NaT": "", "None": "", "nan": ""})
    return pd.DataFrame(
        {
            "broker": m["institution"],
            "account": m["name"],
            "type": m["type"],
            "symbol": m["symbol"],
            "quantity": m["quantity"],
            "cost_per_share": m["cost_per_share"],
            "purchase_date": dates,
        }
    )


def manual_entry(con) -> None:
    st.markdown("---")
    st.markdown("**Enter / edit holdings**")
    st.caption(
        "**One row per purchase (lot)** — enter each buy separately with its own "
        "cost and date for exact returns. Existing rows are loaded for editing; add "
        "rows with the ➕. Use `CASH` as the symbol for a cash balance. "
        "Saving replaces the holdings of every account shown here."
    )
    edited = st.data_editor(
        _current_lots_df(con),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "broker": st.column_config.TextColumn("Broker / institution", required=True),
            "account": st.column_config.TextColumn("Account", required=True),
            "type": st.column_config.SelectboxColumn(
                "Type", options=list(ACCOUNT_TYPES), default="brokerage"
            ),
            "symbol": st.column_config.TextColumn("Symbol (or CASH)", required=True),
            "quantity": st.column_config.NumberColumn("Quantity", format="%.4f"),
            "cost_per_share": st.column_config.NumberColumn("Cost / share", format="%.4f"),
            "purchase_date": st.column_config.TextColumn("Purchase date (YYYY-MM-DD)"),
        },
    )

    if st.button("Save entries", type="primary"):
        try:
            result = parse_normalized_df(edited)
            if not (result.holdings or result.balances):
                st.warning("Nothing to save — add at least one row with a symbol.")
            else:
                st.session_state["import_msg"] = f"Saved {persist(con, result)}."
                st.rerun()
        except Exception as exc:
            st.error(f"Save failed: {exc}")


ETRADE_GUIDE = """
**E\\*TRADE has a real CSV export.**

1. Sign in at **etrade.com** (the website — the mobile app can't export).
2. Go to **Accounts → Portfolios**.
3. Pick the account you want from the account dropdown.
4. Find the **Download** control above/beside the holdings table (a download
   icon, sometimes labeled *Download* or *Export*).
5. Choose the spreadsheet/**CSV** option and save the file.
6. Back here, select **E\\*TRADE export** and upload that file.

The export already contains everything needed — `Symbol`, `Qty`, `Price Paid`,
and a *Cash & Cash Alternatives* line. The parser maps those automatically and
turns the cash line into an account balance. No editing needed.

⚠️ **Cost basis is *average*** in this export — one blended row per symbol. The
total return is still correct, but you won't see per-purchase (lot) returns. For
exact lots from E\\*TRADE, use its tax-lot / *Gains & Losses* export, or enter the
lots in the grid below.
"""

ROBINHOOD_GUIDE = """
**Robinhood has no positions export — but every purchase is in your order
history, and that's your lot data.** Enter one row per buy for exact returns.

1. Open a stock in Robinhood (**robinhood.com** or the app) and scroll to
   **History** — your orders for that stock. Each **Buy** you still hold is a lot.
2. Note its **shares**, **fill price**, and **date**.
3. With **Normalized template** selected, add **one row per buy** in the manual
   grid below — `broker=robinhood`, `account=Individual`, `type=brokerage`,
   `symbol`, `quantity=`shares of that buy, `cost_per_share=`fill price,
   `purchase_date=`date. (Two buys of the same stock = two rows.)
4. For uninvested cash, add a `symbol=CASH` row with `quantity=` your cash.

**Faster for many positions:** *Account → Menu → Reports and statements →
Generate report → Account activity (CSV)* lists every order in one file — copy the
buy rows into the grid.

**If you've sold part of a position:** only enter the lots you still hold.
Robinhood disposes oldest-first (FIFO) by default unless you picked specific lots.
(The **Average Cost** shown on a stock's page is blended — fine for a rough total,
but enter individual buys here for exact per-lot returns.)
"""


def import_tab(con) -> None:
    st.subheader("Import holdings")

    # Surface the result of an import that triggered a rerun (so the Overview/
    # Holdings tabs already reflect the new data when the message shows).
    msg = st.session_state.pop("import_msg", None)
    if msg:
        st.success(msg)

    # Tutorials live at the top, collapsed by default.
    st.markdown("**How to export your data**")
    with st.expander("E\\*TRADE — download a portfolio CSV", expanded=False):
        st.markdown(ETRADE_GUIDE)
    with st.expander("Robinhood — get your holdings in", expanded=False):
        st.markdown(ROBINHOOD_GUIDE)

    st.markdown("---")

    source_type = st.radio(
        "File type",
        ["Normalized template", "E*TRADE export"],
        help="Robinhood: use the normalized template. E*TRADE: upload its native export.",
        horizontal=True,
    )

    if source_type == "E*TRADE export":
        account_name = st.text_input(
            "Account name",
            value="Individual",
            help="Label for this E*TRADE account — its export doesn't include one.",
        )
        uploaded = st.file_uploader("Upload CSV", type=["csv"])
        if uploaded is not None and st.button("Import file"):
            try:
                summary = do_import(con, EtradeCSVSource(uploaded, account=account_name))
                st.session_state["import_msg"] = f"Imported {summary}."
                st.rerun()
            except Exception as exc:  # surface parse errors to the user
                st.error(f"Import failed: {exc}")
        return

    # Normalized template: CSV upload OR manual entry below.
    uploaded = st.file_uploader("Upload CSV", type=["csv"])
    if uploaded is not None and st.button("Import file"):
        try:
            summary = do_import(con, NormalizedCSVSource(uploaded))
            st.session_state["import_msg"] = f"Imported {summary}."
            st.rerun()
        except Exception as exc:  # surface parse errors to the user
            st.error(f"Import failed: {exc}")

    template_path = os.path.join(
        _PROJECT_ROOT, "data", "templates", "normalized_holdings_template.csv"
    )
    if os.path.exists(template_path):
        with open(template_path, "rb") as fh:
            st.download_button(
                "Download blank template",
                fh.read(),
                file_name="normalized_holdings_template.csv",
                mime="text/csv",
            )

    manual_entry(con)


def sidebar(con) -> None:
    st.sidebar.header("Data")
    if st.sidebar.button("Refresh prices", use_container_width=True):
        cached_quotes.clear()
        symbols = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM holdings").fetchall()]
        if symbols:
            db.upsert_prices(con, fetch_prices(symbols))
        st.rerun()
    if st.sidebar.button("Clear data", use_container_width=True):
        db.clear_all(con)
        st.rerun()


def main() -> None:
    con = get_connection()

    st.markdown(
        "<h1>Portfolio <span class='ko-accent'>·</span> 360°</h1>",
        unsafe_allow_html=True,
    )
    st.caption("Local-only view of your investments. Phase 1: E*TRADE + Robinhood.")

    sidebar(con)

    accounts_df = db.load_accounts_df(con)
    holdings_df = db.load_holdings_df(con)
    balances_df = db.load_balances_df(con)

    # Institution filter (drawn from accounts that actually have data).
    if not accounts_df.empty:
        institutions = sorted(accounts_df["institution"].dropna().unique())
        chosen = st.sidebar.multiselect("Filter institutions", institutions, default=institutions)
        keep_ids = set(accounts_df[accounts_df["institution"].isin(chosen)]["account_id"])
        if not holdings_df.empty:
            holdings_df = holdings_df[holdings_df["account_id"].isin(keep_ids)]
        if not balances_df.empty:
            balances_df = balances_df[balances_df["account_id"].isin(keep_ids)]

    prices = ensure_prices(con, holdings_df["symbol"].unique()) if not holdings_df.empty else {}
    enriched = enrich(holdings_df, accounts_df, prices)
    balances_view = balances_with_accounts(balances_df, accounts_df)

    as_of = db.prices_as_of(con)
    if as_of is not None:
        st.caption(f"Prices as of {as_of:%Y-%m-%d %H:%M}. Use *Refresh prices* to update.")

    tab_overview, tab_holdings, tab_import = st.tabs(["Overview", "Holdings", "Import"])
    with tab_overview:
        overview_view.render(enriched, balances_view)
    with tab_holdings:
        holdings_view.render(enriched)
    with tab_import:
        import_tab(con)


if __name__ == "__main__":
    main()
