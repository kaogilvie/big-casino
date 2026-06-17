"""Accounts tab: one row per account with holdings value + cash balance, editable."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import db
from app.models import ACCOUNT_TYPES


def _build_table(enriched: pd.DataFrame, balances: pd.DataFrame) -> pd.DataFrame:
    """Merge enriched holdings + balances into one row per account."""
    if not enriched.empty:
        hv = (
            enriched.groupby("account_id", sort=False)
            .agg(
                institution=("institution", "first"),
                name=("name", "first"),
                type=("type", "first"),
                holdings_value=("market_value", "sum"),
            )
            .reset_index()
        )
    else:
        hv = pd.DataFrame(columns=["account_id", "institution", "name", "type", "holdings_value"])

    if not balances.empty:
        cash = balances[["account_id", "balance"]].copy()
    else:
        cash = pd.DataFrame(columns=["account_id", "balance"])

    # Accounts that only have a balance (no holdings) come from balances table
    if not hv.empty and not cash.empty:
        table = hv.merge(cash, on="account_id", how="outer")
    elif not hv.empty:
        table = hv.copy()
        table["balance"] = 0.0
    elif not cash.empty:
        # Pull metadata from balances df if available
        meta_cols = [c for c in ["institution", "name", "type"] if c in balances.columns]
        table = balances[["account_id", "balance"] + meta_cols].copy()
        table["holdings_value"] = 0.0
    else:
        return pd.DataFrame()

    # Fill missing metadata for outer-joined rows
    if not balances.empty and "institution" in balances.columns:
        bal_meta = balances[["account_id"] + [c for c in ["institution", "name", "type"] if c in balances.columns]]
        for col in ["institution", "name", "type"]:
            if col in bal_meta.columns and col in table.columns:
                mask = table[col].isna()
                if mask.any():
                    table.loc[mask, col] = table.loc[mask, "account_id"].map(
                        bal_meta.set_index("account_id")[col]
                    )

    table["holdings_value"] = table["holdings_value"].fillna(0.0)
    table["balance"] = table["balance"].fillna(0.0)
    table["total_value"] = table["holdings_value"] + table["balance"]
    return table.sort_values("total_value", ascending=False).reset_index(drop=True)


def render(enriched: pd.DataFrame, balances: pd.DataFrame, con) -> None:
    st.subheader("Accounts")

    if enriched.empty and balances.empty:
        st.info("No accounts yet. Import a CSV from the Import tab to get started.")
        return

    table = _build_table(enriched, balances)
    if table.empty:
        st.info("No accounts yet.")
        return

    # ── Editable grid ────────────────────────────────────────────────
    edit_df = table[["account_id", "institution", "name", "type",
                      "holdings_value", "balance", "total_value"]].copy()

    edited = st.data_editor(
        edit_df,
        column_config={
            "account_id":     st.column_config.TextColumn("ID", disabled=True, width="small"),
            "institution":    st.column_config.TextColumn("Institution"),
            "name":           st.column_config.TextColumn("Account Name"),
            "type":           st.column_config.SelectboxColumn("Type", options=list(ACCOUNT_TYPES)),
            "holdings_value": st.column_config.NumberColumn("Holdings", format="$%.2f", disabled=True),
            "balance":        st.column_config.NumberColumn("Cash Balance", format="$%.2f", disabled=True),
            "total_value":    st.column_config.NumberColumn("Total Value", format="$%.2f", disabled=True),
        },
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key="accounts_editor",
    )

    if st.button("Save changes", type="primary", key="accounts_save"):
        changed = 0
        errors = []
        for i, row in edited.iterrows():
            orig = edit_df.iloc[i]
            if (row["institution"] != orig["institution"]
                    or row["name"] != orig["name"]
                    or row["type"] != orig["type"]):
                try:
                    db.rename_account(
                        con,
                        old_account_id=orig["account_id"],
                        institution=str(row["institution"] or "").strip(),
                        name=str(row["name"] or "").strip(),
                        account_type=str(row["type"] or "brokerage"),
                    )
                    changed += 1
                except Exception as exc:
                    errors.append(f"{orig['name']}: {exc}")
        if errors:
            for e in errors:
                st.error(e)
        elif changed:
            st.success(f"Updated {changed} account(s).")
            st.rerun()
        else:
            st.info("No changes detected.")

    # ── Totals ───────────────────────────────────────────────────────
    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("Holdings", f"${table['holdings_value'].sum():,.2f}")
    c2.metric("Cash", f"${table['balance'].sum():,.2f}")
    c3.metric("Total", f"${table['total_value'].sum():,.2f}")
