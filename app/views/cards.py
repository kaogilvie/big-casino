"""Credit Cards tab: one row per card with what you owe and what's due.

Current balance comes from the `balances` table (live amount owed); statement
balance, minimum payment, and due date come from `card_details` (Plaid
liabilities). The headline number is the **statement balance** — pay that by the
due date to avoid interest.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st


def _money(x) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"${x:,.2f}"


def _due_label(due) -> str:
    if due is None or pd.isna(due):
        return "—"
    d = pd.to_datetime(due).date()
    days = (d - date.today()).days
    when = d.strftime("%b %d, %Y")
    if days < 0:
        return f"{when} (overdue)"
    if days == 0:
        return f"{when} (today)"
    return f"{when} ({days}d)"


def render(balances: pd.DataFrame, card_details: pd.DataFrame, con) -> None:
    st.subheader("Credit Cards")

    if balances.empty or "type" not in balances.columns:
        st.info("No credit cards yet. Connect a card via Plaid in the Import tab.")
        return

    cards = balances[balances["type"] == "credit_card"].copy()
    if cards.empty:
        st.info("No credit cards yet. Connect a card via Plaid in the Import tab.")
        return

    # Join in statement detail.
    if card_details is not None and not card_details.empty:
        cards = cards.merge(card_details, on="account_id", how="left")
    else:
        for col in ["statement_balance", "statement_date", "due_date", "minimum_payment"]:
            cards[col] = pd.NA

    cards["Account"] = (
        cards.get("institution", pd.Series("?", index=cards.index)).fillna("?")
        + " · "
        + cards.get("name", cards["account_id"]).fillna("?")
    )

    # ── Headline metrics ──────────────────────────────────────────────
    total_owed = float(cards["balance"].fillna(0).sum())
    total_statement = float(cards["statement_balance"].fillna(0).sum())
    total_min = float(cards["minimum_payment"].fillna(0).sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Current balance (owed)", _money(total_owed))
    c2.metric("Statement balance (to avoid interest)", _money(total_statement))
    c3.metric("Minimum due", _money(total_min))

    st.markdown("---")

    # ── Per-card table ────────────────────────────────────────────────
    show = pd.DataFrame({
        "Card": cards["Account"],
        "Current balance": cards["balance"].map(_money),
        "Statement balance": cards["statement_balance"].map(_money),
        "Min. payment": cards["minimum_payment"].map(_money),
        "Payment due": cards["due_date"].map(_due_label),
    })

    st.dataframe(show, use_container_width=True, hide_index=True)
    st.caption(
        "**Statement balance** is what to pay by the due date to avoid interest. "
        "Statement detail comes from Plaid; cards connected without the liabilities "
        "product show only the current balance."
    )
