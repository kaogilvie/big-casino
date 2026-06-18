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
from app.sources.betterment_csv import BettermentCSVSource
from app.sources.betterment_pdf import BettermentStatementPDFSource
from app.sources.chase_cc_pdf import ChaseCCPDFSource
from app.sources.etrade_csv import EtradeCSVSource
from app.sources.normalized_csv import NormalizedCSVSource, parse_normalized_df
from app.sources.plaid import PlaidItemSource, exchange_public_token, remove_item
from app import plaid_client as plaid_cfg
from app.theme import apply_theme
from app.views import accounts as accounts_view
from app.views import cards as cards_view
from app.views import holdings as holdings_view
from app.views import overview as overview_view

st.set_page_config(page_title="Big Casino", page_icon="🎰", layout="wide")
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
    if getattr(result, "cards", None):
        db.upsert_card_details(con, result.cards)
    return result.summary()


def do_import(con, source) -> str:
    return persist(con, source.fetch())


def persist_append(con, result) -> str:
    """Additive save for manual entry: new lots are appended (never replacing an
    account's existing lots) and cash is added to any existing balance."""
    db.upsert_accounts(con, result.accounts)
    db.append_holdings(con, result.holdings)
    db.add_balances(con, result.balances)
    return result.summary()


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


# Defaults pre-filled in the Robinhood entry grid so you don't retype them.
_ROBINHOOD_DEFAULTS = {"broker": "Robinhood", "account": "Individual", "type": "brokerage"}


def _robinhood_starter_df() -> pd.DataFrame:
    """Blank grid seeded with one Robinhood/Individual row to type a lot into."""
    df = _empty_manual_df()
    df.loc[0] = {c: _ROBINHOOD_DEFAULTS.get(c, "") for c in _MANUAL_COLUMNS}
    return df


def manual_entry(con) -> None:
    st.markdown("---")
    st.markdown("**Enter holdings**")
    st.caption(
        "**One row per purchase (lot)** — enter each buy separately with its own "
        "cost and date for exact returns. `Broker`/`account` default to "
        "Robinhood/Individual (blank rows inherit them). Add rows with the ➕. Use "
        "`CASH` as the symbol for a cash balance. Saving **appends** these rows to "
        "your existing holdings — it never replaces what's already there."
    )
    edited = st.data_editor(
        _robinhood_starter_df(),
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
        with st.spinner("Saving…"):
            try:
                edited = edited.copy()
                for col, default in _ROBINHOOD_DEFAULTS.items():
                    edited[col] = edited[col].replace("", pd.NA).fillna(default)
                result = parse_normalized_df(edited)
                if not (result.holdings or result.balances):
                    st.warning("Nothing to save — add at least one row with a symbol.")
                else:
                    msg = f"Saved {persist_append(con, result)}."
                    st.success(msg)
                    st.session_state["import_msg"] = msg
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
3. With **Robinhood template** selected, add **one row per buy** in the manual
   grid below — `broker` and `account` are pre-filled (Robinhood / Individual);
   just enter `symbol`, `quantity=`shares of that buy, `cost_per_share=`fill
   price, `purchase_date=`date. (Two buys of the same stock = two rows.)
4. For uninvested cash, add a `symbol=CASH` row with `quantity=` your cash.

**Faster for many positions:** *Account → Menu → Reports and statements →
Generate report → Account activity (CSV)* lists every order in one file — copy the
buy rows into the grid.

**If you've sold part of a position:** only enter the lots you still hold.
Robinhood disposes oldest-first (FIFO) by default unless you picked specific lots.
(The **Average Cost** shown on a stock's page is blended — fine for a rough total,
but enter individual buys here for exact per-lot returns.)
"""


BETTERMENT_GUIDE = """
**The easiest path is your monthly statement PDF** — it contains ending share
counts for every ETF across all your goals, plus your Cash Reserve balance.
No manual data entry needed.

**How to download it**

1. Sign in at **betterment.com**.
2. Go to **Documents** (top-right menu or account settings).
3. Under **Statements**, find your most recent **Monthly Statement** and download
   the PDF.
4. Upload it here with **Betterment statement (PDF)** selected.

**What gets imported**

| source | what it becomes |
|---|---|
| Each investing goal (Safety Net, Retirement goal, etc.) | an Account + its ETF holdings |
| Roth IRA / Traditional IRA | an Account (type = retirement) + holdings |
| Cash Reserve ending balance | a Balance on a "bank" account |

⚠️ The monthly statement does not include cost basis, so unrealized return will
show as the full market value until you add cost basis separately. Use
**Betterment CSV** if you want to enter cost basis manually.

**Re-importing**

Drop in the latest monthly statement any time — the import replaces all prior
Betterment positions with the new end-of-month snapshot.
"""


_PLAID_RESULT_FILE = os.path.join(_PROJECT_ROOT, "data", "plaid_result.json")
_PLAID_SERVER_URL = "http://localhost:3001"


def _consume_plaid_result(con) -> bool:
    """Read plaid_result.json written by the Express server, import it, delete it.

    Returns True if a result was consumed.
    """
    if not os.path.exists(_PLAID_RESULT_FILE):
        return False
    import json
    try:
        with open(_PLAID_RESULT_FILE) as f:
            data = json.load(f)
        os.remove(_PLAID_RESULT_FILE)
        item_id = data["item_id"]
        access_token = data["access_token"]
        institution = data.get("institution", "Unknown")
        db.upsert_plaid_item(con, item_id, access_token, institution)
        client = plaid_cfg.get_client()
        result = PlaidItemSource(client, access_token, institution).fetch()
        persist(con, result)
        st.success(f"Connected {institution} — imported {result.summary()}.")
        return True
    except Exception as exc:
        st.error(f"Plaid import failed: {exc}")
        return False


def _plaid_section(con) -> None:
    st.markdown("**Connected accounts (Plaid)**")

    # ── Consume result written by the Express server ──────────────────
    if _consume_plaid_result(con):
        st.rerun()

    # ── Show connected items ──────────────────────────────────────────
    items_df = db.load_plaid_items(con)
    if not items_df.empty:
        for _, row in items_df.iterrows():
            c1, c2, c3, c4 = st.columns([4, 2, 2, 2])
            c1.markdown(f"**{row['institution']}**")
            c2.caption(f"Connected {str(row['created_at'])[:10]}")
            with c3:
                if st.button("Refresh", key=f"plaid_refresh_{row['item_id']}",
                             use_container_width=True):
                    try:
                        client = plaid_cfg.get_client()
                        token = db.get_plaid_access_token(con, row["item_id"])
                        result = PlaidItemSource(client, token, row["institution"]).fetch()
                        persist(con, result)
                        st.success(f"Refreshed {row['institution']} — {result.summary()}.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Refresh failed: {exc}")
            with c4:
                if st.button("Delete", key=f"plaid_delete_{row['item_id']}",
                             use_container_width=True):
                    # Best-effort: invalidate the token at Plaid (stops billing).
                    try:
                        client = plaid_cfg.get_client()
                        token = db.get_plaid_access_token(con, row["item_id"])
                        if token:
                            remove_item(client, token)
                    except Exception:
                        pass  # creds may already be invalid — still purge locally
                    db.delete_plaid_connection(con, row["item_id"], row["institution"])
                    st.success(f"Removed {row['institution']} and its imported data.")
                    st.rerun()
    else:
        st.caption("No accounts connected yet.")

    # ── Connect new account ───────────────────────────────────────────
    if not plaid_cfg.is_configured():
        st.warning("Plaid not configured — add PLAID_CLIENT_ID and PLAID_SECRET to your .env file.")
        return

    st.markdown(
        f"1. Open **[localhost:3001]({_PLAID_SERVER_URL})** in a new tab and connect your account.\n"
        "2. Once you see '✓ Connected!', come back here and click **Finish connecting**."
    )
    if st.button("Finish connecting", key="plaid_finish", type="primary"):
        if not _consume_plaid_result(con):
            st.warning("No connection found yet — complete the Plaid flow in the other tab first.")
        else:
            st.rerun()


def import_tab(con) -> None:
    st.subheader("Import holdings")

    # Surface the result of an import that triggered a rerun (so the Overview/
    # Holdings tabs already reflect the new data when the message shows).
    msg = st.session_state.pop("import_msg", None)
    if msg:
        st.success(msg)

    _plaid_section(con)
    st.markdown("---")

    source_type = st.radio(
        "File type",
        ["Robinhood template", "E*TRADE export", "Betterment statement (PDF)", "Betterment CSV", "Chase credit card (PDF)"],
        help="Robinhood: enter lots in the grid (or upload a template CSV). "
        "E*TRADE: upload its native export. Betterment: upload the monthly statement PDF "
        "(recommended) or a manually-built CSV.",
        horizontal=True,
    )

    if source_type == "Betterment statement (PDF)":
        with st.expander("Betterment — get your monthly statement", expanded=False):
            st.markdown(BETTERMENT_GUIDE)
        uploaded = st.file_uploader("Upload Betterment monthly statement", type=["pdf"])
        if uploaded is not None and st.button("Import file"):
            try:
                summary = do_import(con, BettermentStatementPDFSource(uploaded))
                st.session_state["import_msg"] = f"Imported {summary}."
                st.rerun()
            except Exception as exc:
                st.error(f"Import failed: {exc}")
        return

    if source_type == "Betterment CSV":
        with st.expander("Betterment — build your holdings CSV", expanded=False):
            st.markdown(BETTERMENT_GUIDE)
        with open(os.path.join(_PROJECT_ROOT, "samples", "betterment_sample.csv"), "rb") as fh:
            st.download_button(
                "Download sample CSV",
                fh.read(),
                file_name="betterment_sample.csv",
                mime="text/csv",
            )
        uploaded = st.file_uploader("Upload Betterment CSV", type=["csv"])
        if uploaded is not None and st.button("Import file"):
            try:
                summary = do_import(con, BettermentCSVSource(uploaded))
                st.session_state["import_msg"] = f"Imported {summary}."
                st.rerun()
            except Exception as exc:
                st.error(f"Import failed: {exc}")
        return

    if source_type == "E*TRADE export":
        with st.expander("E\\*TRADE — download a portfolio CSV", expanded=False):
            st.markdown(ETRADE_GUIDE)
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

    if source_type == "Chase credit card (PDF)":
        with st.expander("Chase — download your statement", expanded=False):
            st.markdown(
                "1. Sign in at **chase.com**.\n"
                "2. Go to your credit card account → **Statements & documents**.\n"
                "3. Download the most recent **PDF statement**.\n"
                "4. Upload it here.\n\n"
                "The parser reads your **New Balance** (current amount owed) and adds "
                "it as a liability that is netted out of your net worth."
            )
        label = st.text_input(
            "Account label (optional)",
            placeholder="e.g. Chase Sapphire — leave blank to use last 4 digits",
        )
        uploaded = st.file_uploader("Upload Chase statement PDF", type=["pdf"])
        if uploaded is not None and st.button("Import file"):
            try:
                source = ChaseCCPDFSource(uploaded, account_label=label.strip() or None)
                summary = do_import(con, source)
                st.session_state["import_msg"] = f"Imported {summary}."
                st.rerun()
            except Exception as exc:
                st.error(f"Import failed: {exc}")
        return

    # Robinhood template: CSV upload OR manual entry below.
    with st.expander("Robinhood — get your holdings in", expanded=False):
        st.markdown(ROBINHOOD_GUIDE)
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
        "<h1>Big Casino <span style='font-size:0.5em;font-weight:400;color:#888;'>by &amp;KO</span></h1>",
        unsafe_allow_html=True,
    )
    st.caption("Your personal finance dashboard, local and private.")

    sidebar(con)

    accounts_df = db.load_accounts_df(con)
    holdings_df = db.load_holdings_df(con)
    balances_df = db.load_balances_df(con)

    prices = ensure_prices(con, holdings_df["symbol"].unique()) if not holdings_df.empty else {}
    enriched = enrich(holdings_df, accounts_df, prices)
    balances_view = balances_with_accounts(balances_df, accounts_df)
    card_details_df = db.load_card_details_df(con)

    as_of = db.prices_as_of(con)
    if as_of is not None:
        st.caption(f"Prices as of {as_of:%Y-%m-%d %H:%M}. Use *Refresh prices* to update.")

    tab_overview, tab_holdings, tab_accounts, tab_cards, tab_import = st.tabs(
        ["Overview", "Holdings", "Accounts", "Credit Cards", "Import"]
    )
    with tab_overview:
        overview_view.render(enriched, balances_view)
    with tab_holdings:
        holdings_view.render(enriched, con)
    with tab_accounts:
        accounts_view.render(enriched, balances_view, con)
    with tab_cards:
        cards_view.render(balances_view, card_details_df, con)
    with tab_import:
        import_tab(con)


if __name__ == "__main__":
    main()
